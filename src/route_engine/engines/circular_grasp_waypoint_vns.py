"""
src/route_engine/engines/circular_grasp_waypoint_vns.py

(버전 C) GRASP + VNS(Variable Neighborhood Search) — 비교/벤치마크용 신규 구현.
기존 circular_grasp.py/grasp_solver.py는 이 작업으로 수정하지 않는다.

경유지 후보 풀은 waypoint_pool.py::WaypointPoolGenerator(p1 기준 cutoff SSSP 단일 풀)를
쓴다 — 이전에 이 파일이 직접 만들던 Haversine 사전필터 기반 거리링은 제거했다.
"""

import logging
import random
from dataclasses import replace
from typing import Optional

import networkx as nx

from src.interfaces.schema.walk_schema import WalkMode, WalkRouteResponse, WalkRouteStatus
from src.route_engine.engines.circular_grasp_waypoint_vnd import CircularGraspWaypointVndEngine
from src.route_engine.engines.grasp_waypoint_common import (
    BuildCycleRoute,
    DEFAULT_CONFIG,
    GraspConfig,
    Route,
    RouteGeometryMetrics,
    SelectionStatus,
    _CostCache,
    _INFEASIBLE,
    _edge_overlap_ratio,
    _sum_edge_length,
    better,
    compute_route_geometry_metrics,
    construct_initial_route,
    determine_selection_status,
    evaluate_route,
    format_optional,
    format_optional_list,
)
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.engines.waypoint_pool import WaypointPoolGenerator, WaypointPoolResult
from src.schema.route_schema import CircularRouteInput

logger = logging.getLogger(__name__)

_SEED = 42
_MAX_SHAKE_LEVEL = 4


class CircularGraspWaypointVnsEngine:
    """
    GRASP으로 경유지(cfg.num_waypoints개)를 waypoint_pool.py가 만든 후보 풀 중에서
    선택한 뒤, VND(버전 B, CircularGraspWaypointVndEngine)를 지역탐색 단계로 그대로
    재사용한다(중복 구현 금지). VND가 지역 최적에 도달하면 Shake로 임시 경로를 만들어
    교란하고, 그 경로에 다시 VND를 실행한다. 교란 직후 결과가 즉시 더 좋아야 하는 것은
    아니며, VND가 끝난 최종 결과가 기존 경로보다 좋아질 때만 현재 경로를 갱신한다
    (그렇지 않으면 나쁜 경로가 최종해로 채택된다).

    Shake level 1·2는 "넓은 후보 집합에서 무작위 교체"를 랭킹 없이 풀 전체에서 균등
    무작위로 뽑아 구현한다(구축 단계의 RCL보다 덜 그리디한 교란이 목적). Shake level 3은
    "동일 경유지 조합의 대체 A* 경로 선택"이 아니라 **"한 구간의 엣지 일부를 그래프
    사본에서 일시 차단하고 A*를 재실행"**으로 구현한다 — VND의 AlternativeSegment
    이웃이 비활성 상태라, A*가 동일 출발-도착 쌍에 대해 다른 경로를 낼 수 있는 유일한
    방법이기 때문이다.
    """

    def __init__(
        self,
        inp: CircularRouteInput,
        G: nx.Graph,
        mode: str = "distance",
        seed: int = _SEED,
        config: GraspConfig = DEFAULT_CONFIG,
        num_waypoints: Optional[int] = None,
    ):
        self.inp = inp
        # G.copy() 안 함(2026-08-30 재검토) — grasp_waypoint_common.py/waypoint_pool.py/
        # PathUtils는 읽기 전용이고 calculate_custom_score()도 안 부른다(mode="distance"
        # 전용). 이유는 circular_grasp_waypoint_local.py::__init__ 주석 참고. 그래프를
        # 변형하는 코드를 추가하면 이 가정이 깨지므로 다시 복사해야 한다(benchmarks/
        # benchmark.py 모듈 docstring의 "그래프 공유·변형 규칙" 참고).
        #
        # 이 클래스는 특히 복사를 안 하는 효과가 크다 — 예전엔 아래 CircularGraspWaypointVndEngine
        # 생성 시 그 __init__이 자기 몫으로 또 G.copy()를 해서(16만 노드 기준 약 1.7초) 만든
        # 사본을 바로 다음 줄에서 self.G로 덮어써 버렸다(:83). 즉 인스턴스 생성마다 약 1.7초를
        # 통째로 낭비했다 — G.copy()를 아예 없애 이 낭비도 함께 사라진다.
        self.G = G
        self.mode = mode
        self.seed = seed
        self.config = config if num_waypoints is None else replace(config, num_waypoints=num_waypoints)
        self.utils = PathUtils(self.G)
        self.cost_cache = _CostCache(self.G, mode=mode)
        self.pool_generator = WaypointPoolGenerator(self.G)
        # VND 단계는 같은 그래프·같은 캐시를 공유하도록 인스턴스를 만든 뒤 덮어쓴다.
        # self.G 재대입은 이제(둘 다 복사를 안 하므로) 같은 객체를 다시 가리키는 것이라
        # 실질적으로는 no-op이지만, utils/cost_cache는 VndEngine.__init__이 자기 몫으로
        # 새로 만든 인스턴스이므로 VNS의 것으로 실제로 교체해야 한다(GRASP 반복 전체에서
        # A* 캐시를 공유하기 위함 — 안 하면 VND 쪽 캐시가 매번 비어 시작한다).
        self._vnd_engine = CircularGraspWaypointVndEngine(inp, self.G, mode=mode, seed=seed, config=self.config)
        self._vnd_engine.G = self.G
        self._vnd_engine.utils = self.utils
        self._vnd_engine.cost_cache = self.cost_cache
        self.last_selection_status: Optional[str] = None  # 벤치마크/로그 전용(요청서 §3.6, §6)
        self.last_route: Optional[Route] = None  # 벤치마크가 구간 거리 등을 재계산할 때 씀
        self.last_geometry_metrics: Optional[RouteGeometryMetrics] = None  # 원형성 진단 지표(2026-08-30)

    def run(self) -> list[WalkRouteResponse]:
        logger.info(
            "GRASP+VNS(경유지 선택) 경로 생성 엔진을 시작합니다: target_km=%s, mode=%s",
            self.inp.target_km, self.mode,
        )
        start = self.utils.find_nearest_node(self.inp.start_lat, self.inp.start_lon)
        if start is None:
            logger.warning("출발 노드를 찾지 못했습니다.")
            return [WalkRouteResponse(
                status=WalkRouteStatus.NO_NEAREST_START_NODE,
                mode=WalkMode.CIRCULAR_RANDOM, coordinates=[], total_km=0.0,
            )]

        nodes = self.find_path(start, self.inp.target_km or 3.0)
        if not nodes or len(nodes) < 2:
            logger.warning("경로가 비어 있습니다.")
            return [WalkRouteResponse(
                status=WalkRouteStatus.NO_PATH,
                mode=WalkMode.CIRCULAR_RANDOM, coordinates=[], total_km=0.0,
            )]

        pruned = self.utils.prune_dead_ends(nodes)
        coords = self.utils.extract_coordinates(pruned)
        total_km = round(self.utils.calc_distance(pruned) / 1000, 2)
        return [WalkRouteResponse(
            status=WalkRouteStatus.SUCCESS if coords else WalkRouteStatus.NO_PATH,
            mode=WalkMode.CIRCULAR_RANDOM, coordinates=coords, total_km=total_km,
        )]

    def find_path(self, start_node: int, target_km: float = 3.0) -> list[int]:
        target_m = target_km * 1000
        rng = random.Random(self.seed)

        start_data = self.G.nodes[start_node]
        pool_result = self.pool_generator.build_pool(
            start_data.get("lat", 0.0), start_data.get("lon", 0.0), target_km,
            pairwise_cache_rows=self.config.pairwise_cache_rows,
        )
        if pool_result is None or not pool_result.pool_nodes:
            logger.warning("경유지 후보 풀을 만들지 못했습니다.")
            self.last_selection_status = SelectionStatus.NO_VALID_WAYPOINT_PAIR
            return [start_node]

        best_route, best_obj = None, _INFEASIBLE
        had_valid_waypoint_pair = False
        for _ in range(self.config.grasp_iters):
            construction = construct_initial_route(self.G, self.cost_cache, pool_result, start_node, target_m, rng, self.config)
            had_valid_waypoint_pair = had_valid_waypoint_pair or construction.had_valid_waypoint_pair
            current = construction.route
            if current is None:
                continue
            current = self._vnd_engine.vnd(current, pool_result, start_node, target_m)
            current = self._vns_loop(current, pool_result, start_node, target_m, rng)

            obj = evaluate_route(current, target_m, target_m * self.config.distance_tolerance_ratio)
            if best_route is None or better(obj, best_obj):
                best_obj, best_route = obj, current

        self.last_selection_status = determine_selection_status(best_route, best_obj, had_valid_waypoint_pair)
        self.last_route = best_route
        self.last_geometry_metrics = compute_route_geometry_metrics(self.G, self.cost_cache, start_node, best_route, target_m)

        if best_route is None:
            logger.warning(
                "GRASP(경유지 선택, VNS) 후보가 비어 출발 노드만 반환합니다. selection_status=%s",
                self.last_selection_status,
            )
            return [start_node]

        gm = self.last_geometry_metrics
        logger.info(
            "GRASP+VNS 순환 경로 선택: 노드=%d개, 거리오차=%.0fm, 반복률=%.3f, selection_status=%s, "
            "구간거리=%sm, 방위각차=%s도, 균형비=%s, 퇴화의심=%s",
            len(best_route.node_ids), best_obj.distance_error_m, best_obj.repeated_edge_ratio, self.last_selection_status,
            format_optional_list(gm.segment_lengths_m), format_optional_list(gm.waypoint_angle_diffs_deg, 2),
            format_optional(gm.segment_balance_ratio, 3), gm.is_degenerate_loop,
        )
        return best_route.node_ids

    def _vns_loop(
        self, current: Route, pool_result: WaypointPoolResult, start_node: int, target_m: float, rng: random.Random,
    ) -> Route:
        current_obj = evaluate_route(current, target_m, target_m * self.config.distance_tolerance_ratio)
        shake_level = 1
        while shake_level <= _MAX_SHAKE_LEVEL:
            shaken = self._shake(current, pool_result, start_node, target_m, shake_level, rng)
            if shaken is None:
                shake_level += 1
                continue

            candidate = self._vnd_engine.vnd(shaken, pool_result, start_node, target_m)
            candidate_obj = evaluate_route(candidate, target_m, target_m * self.config.distance_tolerance_ratio)

            if better(candidate_obj, current_obj):
                current, current_obj = candidate, candidate_obj
                shake_level = 1  # 개선되면 가장 약한 교란부터 다시
            else:
                shake_level += 1
        return current

    def _shake(
        self, route: Route, pool_result: WaypointPoolResult, start_node: int, target_m: float,
        shake_level: int, rng: random.Random,
    ) -> Optional[Route]:
        if shake_level == 1:
            return self._shake_replace_one(route, pool_result, start_node, rng)
        if shake_level == 2:
            return self._shake_replace_both(pool_result, start_node, rng)
        if shake_level == 3:
            return self._shake_reroute_segment(route, start_node, rng)
        # level 4: 전체 재구축(요청서 범위 밖 — had_valid_waypoint_pair는 메인 GRASP 루프에서만
        # 집계하므로 여기서는 route만 꺼내 쓴다).
        return construct_initial_route(self.G, self.cost_cache, pool_result, start_node, target_m, rng, self.config).route

    def _shake_replace_one(
        self, route: Route, pool_result: WaypointPoolResult, start_node: int, rng: random.Random,
    ) -> Optional[Route]:
        """경유지 하나(위치는 무작위로 고름)를 풀 전체에서 균등 무작위로 교체(구축 단계의
        그리디 RCL보다 훨씬 넓은 후보 집합에서 뽑는 게 목적이라 랭킹 없이 뽑는다)."""
        i = rng.randrange(len(route.waypoints))
        choices = [c for c in pool_result.pool_nodes if c not in route.waypoints]
        if not choices:
            return None
        new_waypoints = list(route.waypoints)
        new_waypoints[i] = rng.choice(choices)
        return BuildCycleRoute(self.G, self.cost_cache.astar_path, start_node, new_waypoints)

    def _shake_replace_both(
        self, pool_result: WaypointPoolResult, start_node: int, rng: random.Random,
    ) -> Optional[Route]:
        """모든 경유지를 풀 전체에서 균등 무작위로(중복 없이) 교체. rng.sample로 한 번에
        N개를 뽑는다 — 기존(N=2 전용) 두 번의 rng.choice 방식과 결과 분포는 동일하지만
        (둘 다 서로 다른 노드 쌍을 균등 무작위로 뽑음), N으로 일반화하면서 소비하는 난수
        시퀀스 자체는 달라진다(시드 재현성이 깨지는 건 아니지만 이전 실행과 노드별 값이
        정확히 일치하진 않는다)."""
        n = self.config.num_waypoints
        if len(pool_result.pool_nodes) < n:
            return None
        new_waypoints = rng.sample(pool_result.pool_nodes, n)
        return BuildCycleRoute(self.G, self.cost_cache.astar_path, start_node, new_waypoints)

    def _shake_reroute_segment(self, route: Route, start_node: int, rng: random.Random) -> Optional[Route]:
        """경로 위 엣지 하나를 무한대 비용으로 일시 차단하고 A*를 재실행해 대체 경로를
        얻는다. 그래프를 복사하지 않는다(_CostCache.astar_path_avoiding_edges 참고) —
        16만 노드 그래프에서 G.copy()를 Shake마다 부르면 감당이 안 된다."""
        node_ids = route.node_ids
        if len(node_ids) < 3:
            return None

        i = rng.randrange(len(node_ids) - 1)
        u, v = node_ids[i], node_ids[i + 1]

        if not self.G.has_edge(u, v):
            return None
        banned = frozenset({frozenset((u, v))})

        stops = [start_node, *route.waypoints, start_node]
        rerouted_nodes: list[int] = []
        for a, b in zip(stops, stops[1:]):
            leg = self.cost_cache.astar_path_avoiding_edges(a, b, banned)
            if leg is None:
                return None
            rerouted_nodes = rerouted_nodes + leg[1:] if rerouted_nodes else leg

        if len(rerouted_nodes) < 2:
            return None
        # BuildCycleRoute와 동일하게 왕복 가지를 미리 제거해 distance_m 기준을 통일한다.
        pruned = self.utils.prune_dead_ends(rerouted_nodes)
        if len(pruned) < 2:
            return None
        return Route(
            node_ids=pruned,
            waypoints=list(route.waypoints),
            distance_m=_sum_edge_length(self.G, pruned),
            repeated_edge_ratio=_edge_overlap_ratio(self.G, pruned),
        )
