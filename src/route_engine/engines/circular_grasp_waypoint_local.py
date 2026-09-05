"""
src/route_engine/engines/circular_grasp_waypoint_local.py

(버전 A) GRASP + 일반 지역개선 — 비교/벤치마크용 신규 구현. 기존
circular_grasp.py(엣지 단위로 전체 경로를 직접 구성하는 방식)와는 알고리즘 구조가 다른
별도 파일이며, 그 파일과 grasp_solver.py는 이 작업으로 수정하지 않는다.

경유지 후보 풀은 waypoint_pool.py::WaypointPoolGenerator(p1 기준 cutoff SSSP 단일 풀)를
쓴다 — 이전에 이 파일이 직접 만들던 Haversine 사전필터 기반 거리링은 제거했다.
"""

import logging
import random
from dataclasses import replace
from typing import Optional

import networkx as nx

from src.interfaces.schema.walk_schema import WalkMode, WalkRouteResponse, WalkRouteStatus
from src.route_engine.engines.grasp_waypoint_common import (
    DEFAULT_CONFIG,
    GraspConfig,
    Route,
    RouteGeometryMetrics,
    SelectionStatus,
    _CostCache,
    _INFEASIBLE,
    better,
    compute_route_geometry_metrics,
    construct_initial_route,
    determine_selection_status,
    evaluate_route,
    format_optional,
    format_optional_list,
    waypoint_replacement_neighbors,
)
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.engines.waypoint_pool import WaypointPoolGenerator
from src.schema.route_schema import CircularRouteInput

logger = logging.getLogger(__name__)

_SEED = 42


class CircularGraspWaypointLocalEngine:
    """
    GRASP으로 경유지(p2, p3) 2개를 waypoint_pool.py가 만든 후보 풀 중에서 선택하고,
    실제 구간 연결은 NetworkX A*(PathUtils.astar_path 경유)가 담당한다(p1→p2→p3→p1).
    그 뒤 WaypointReplacement 이웃 1종만으로 지역개선한다.

    1차 구현은 mode="distance"만 실제로 동작한다(그래프 엣지 속성 length 사용).
    nature_score는 현재 그래프에 로드되지 않으므로(grasp_waypoint_common.py 모듈
    docstring 참고) "natural"/"distance_natural" mode는 EdgeCost()가
    NotImplementedError를 던진다 — 삭제하지 않고 향후 확장 지점으로 남겨둔다.
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
        # G.copy() 안 함(기존 circular_grasp.py 관례와 다름, 2026-08-30 재검토) — 이 클래스와
        # grasp_waypoint_common.py/waypoint_pool.py/PathUtils가 이 파이프라인 안에서 실제로
        # 부르는 메서드는 전부 읽기 전용이고(G.add_*/remove_*/set_*_attributes 등 변형 호출
        # 없음), calculate_custom_score()도 부르지 않는다(mode="distance" 전용이라
        # run_circular_engine_distance_only()를 씀 — custom_score를 그래프에 기록하는
        # run_circular_engine()과 다름). circular_grasp.py류가 매번 복사하는 건 그쪽이
        # calculate_custom_score()로 그래프를 실제로 변형하기 때문— 이 클래스는 해당 없다.
        # 16만 노드 그래프에서 G.copy() 1회가 약 1.7초라 그 비용을 그대로 아낀다. 이후 이
        # 클래스에 그래프를 변형하는 코드를 추가한다면 이 가정이 깨지므로 다시 복사해야 한다
        # (benchmarks/benchmark.py 모듈 docstring의 "그래프 공유·변형 규칙" 참고).
        self.G = G
        self.mode = mode
        self.seed = seed
        # num_waypoints가 주어지면 config 전체를 새로 안 만들어도 이 필드만 덮어쓴다.
        self.config = config if num_waypoints is None else replace(config, num_waypoints=num_waypoints)
        self.utils = PathUtils(self.G)
        self.cost_cache = _CostCache(self.G, mode=mode)
        self.pool_generator = WaypointPoolGenerator(self.G)
        self.last_selection_status: Optional[str] = None  # 벤치마크/로그 전용(요청서 §3.6, §6)
        self.last_route: Optional[Route] = None  # 벤치마크가 d12/d23/d31 등을 재계산할 때 씀
        self.last_geometry_metrics: Optional[RouteGeometryMetrics] = None  # 원형성 진단 지표(2026-08-30)

    def run(self) -> list[WalkRouteResponse]:
        logger.info(
            "GRASP+일반지역개선(경유지 선택) 경로 생성 엔진을 시작합니다: target_km=%s, mode=%s",
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
            route = construction.route
            if route is None:
                continue
            route = self._local_search(route, pool_result, start_node, target_m)
            obj = evaluate_route(route, target_m, target_m * self.config.distance_tolerance_ratio)
            if best_route is None or better(obj, best_obj):
                best_obj, best_route = obj, route

        self.last_selection_status = determine_selection_status(best_route, best_obj, had_valid_waypoint_pair)
        self.last_route = best_route
        self.last_geometry_metrics = compute_route_geometry_metrics(self.G, self.cost_cache.astar_path, start_node, best_route, target_m)

        if best_route is None:
            logger.warning(
                "GRASP(경유지 선택, 일반 지역개선) 후보가 비어 출발 노드만 반환합니다. selection_status=%s",
                self.last_selection_status,
            )
            return [start_node]

        gm = self.last_geometry_metrics
        logger.info(
            "GRASP+일반지역개선 순환 경로 선택: 노드=%d개, 거리오차=%.0fm, 반복률=%.3f, selection_status=%s, "
            "구간거리=%sm, 방위각차=%s도, 균형비=%s, 퇴화의심=%s",
            len(best_route.node_ids), best_obj.distance_error_m, best_obj.repeated_edge_ratio, self.last_selection_status,
            format_optional_list(gm.segment_lengths_m), format_optional_list(gm.waypoint_angle_diffs_deg, 2),
            format_optional(gm.segment_balance_ratio, 3), gm.is_degenerate_loop,
        )
        return best_route.node_ids


    def _local_search(self, route: Route, pool_result, start_node: int, target_m: float) -> Route:
        """단순 지역개선: 개선이 없어질 때까지 WaypointReplacement 이웃에서
        best-improvement를 반복 채택한다."""
        current = route
        current_obj = evaluate_route(current, target_m, target_m * self.config.distance_tolerance_ratio)
        improved = True
        while improved:
            improved = False
            best_neighbor, best_neighbor_obj = current, current_obj
            for neighbor in waypoint_replacement_neighbors(
                self.G, self.cost_cache, pool_result, start_node, current, target_m, self.config
            ):
                neighbor_obj = evaluate_route(neighbor, target_m, target_m * self.config.distance_tolerance_ratio)
                if better(neighbor_obj, best_neighbor_obj):
                    best_neighbor, best_neighbor_obj = neighbor, neighbor_obj
            if better(best_neighbor_obj, current_obj):
                current, current_obj = best_neighbor, best_neighbor_obj
                improved = True
        return current
