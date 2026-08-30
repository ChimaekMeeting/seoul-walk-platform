"""
src/route_engine/engines/circular_grasp_waypoint_vnd.py

(버전 B) GRASP + VND(Variable Neighborhood Descent) — 비교/벤치마크용 신규 구현.
기존 circular_grasp.py/grasp_solver.py는 이 작업으로 수정하지 않는다.

경유지 후보 풀은 waypoint_pool.py::WaypointPoolGenerator(p1 기준 cutoff SSSP 단일 풀)를
쓴다 — 이전에 이 파일이 직접 만들던 Haversine 사전필터 기반 거리링은 제거했다.
"""

import logging
import random
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
    waypoint_pair_replacement_neighbors,
    waypoint_replacement_neighbors,
)
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.engines.waypoint_pool import WaypointPoolGenerator
from src.schema.route_schema import CircularRouteInput

logger = logging.getLogger(__name__)

_SEED = 42

# VND 이웃 목록(요청서가 지정한 이름 그대로). AlternativeSegment(3번째 이웃)는 1차
# 구현에서 비활성 — A*가 동일 출발-도착 쌍에 대해 항상 하나의 경로만 반환하는 현재
# 구조를 확장해야 하므로(요청서 §8), WaypointReplacement/WaypointPairReplacement
# 2종만 등록한다. **현재는 경유지 교체 이웃만 활성화됨.**
_NEIGHBORHOODS = (waypoint_replacement_neighbors, waypoint_pair_replacement_neighbors)


class CircularGraspWaypointVndEngine:
    """
    GRASP으로 경유지(p2, p3)를 waypoint_pool.py가 만든 후보 풀 중에서 선택한 뒤, 이웃을
    WaypointReplacement → WaypointPairReplacement 순서로 바꿔가며 개선한다. 어느
    이웃에서든 개선을 찾으면 다시 첫 이웃부터 검사한다(VND 핵심 규칙).
    """

    def __init__(
        self,
        inp: CircularRouteInput,
        G: nx.Graph,
        mode: str = "distance",
        seed: int = _SEED,
        config: GraspConfig = DEFAULT_CONFIG,
    ):
        self.inp = inp
        # G.copy() 안 함(2026-08-30 재검토) — 이 클래스가 부르는 것(grasp_waypoint_common.py/
        # waypoint_pool.py/PathUtils)은 전부 읽기 전용이고 calculate_custom_score()도 안
        # 부른다(mode="distance" 전용). 이유는 circular_grasp_waypoint_local.py::__init__
        # 주석 참고 — 그래프를 변형하는 코드를 추가하면 이 가정이 깨지므로 다시 복사해야
        # 한다(benchmarks/benchmark.py 모듈 docstring의 "그래프 공유·변형 규칙" 참고).
        self.G = G
        self.mode = mode
        self.seed = seed
        self.config = config
        self.utils = PathUtils(self.G)
        self.cost_cache = _CostCache(self.G, mode=mode)
        self.pool_generator = WaypointPoolGenerator(self.G)
        self.last_selection_status: Optional[str] = None  # 벤치마크/로그 전용(요청서 §3.6, §6)
        self.last_route: Optional[Route] = None  # 벤치마크가 d12/d23/d31 등을 재계산할 때 씀
        self.last_geometry_metrics: Optional[RouteGeometryMetrics] = None  # 원형성 진단 지표(2026-08-30)

    def run(self) -> list[WalkRouteResponse]:
        logger.info(
            "GRASP+VND(경유지 선택) 경로 생성 엔진을 시작합니다: target_km=%s, mode=%s",
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
            route = self.vnd(route, pool_result, start_node, target_m)
            obj = evaluate_route(route, target_m, self.config.distance_tolerance_m)
            if best_route is None or better(obj, best_obj):
                best_obj, best_route = obj, route

        self.last_selection_status = determine_selection_status(best_route, best_obj, had_valid_waypoint_pair)
        self.last_route = best_route
        self.last_geometry_metrics = compute_route_geometry_metrics(self.G, self.cost_cache, start_node, best_route, target_m)

        if best_route is None:
            logger.warning(
                "GRASP(경유지 선택, VND) 후보가 비어 출발 노드만 반환합니다. selection_status=%s",
                self.last_selection_status,
            )
            return [start_node]

        gm = self.last_geometry_metrics
        logger.info(
            "GRASP+VND 순환 경로 선택: 노드=%d개, 거리오차=%.0fm, 반복률=%.3f, selection_status=%s, "
            "d12=%sm, d23=%sm, d31=%sm, 방위각차=%s도, 균형비=%s, 퇴화의심=%s",
            len(best_route.node_ids), best_obj.distance_error_m, best_obj.repeated_edge_ratio, self.last_selection_status,
            format_optional(gm.segment_p1_p2_m), format_optional(gm.segment_p2_p3_m), format_optional(gm.segment_p3_p1_m),
            format_optional(gm.waypoint_angle_diff_deg), format_optional(gm.segment_balance_ratio, 3), gm.is_degenerate_loop,
        )
        return best_route.node_ids

    def vnd(self, route: Route, pool_result, start_node: int, target_m: float) -> Route:
        """VND: 이웃 목록을 순서대로 검사하다가 개선을 찾으면 첫 이웃부터 다시 시작한다.
        VNS(circular_grasp_waypoint_vns.py)가 지역탐색 단계로 이 메서드를 그대로 재사용한다."""
        current = route
        current_obj = evaluate_route(current, target_m, self.config.distance_tolerance_m)
        idx = 0
        while idx < len(_NEIGHBORHOODS):
            neighborhood_fn = _NEIGHBORHOODS[idx]
            best_neighbor, best_neighbor_obj = current, current_obj
            for neighbor in neighborhood_fn(self.G, self.cost_cache, pool_result, start_node, current, target_m, self.config):
                neighbor_obj = evaluate_route(neighbor, target_m, self.config.distance_tolerance_m)
                if better(neighbor_obj, best_neighbor_obj):
                    best_neighbor, best_neighbor_obj = neighbor, neighbor_obj
            if better(best_neighbor_obj, current_obj):
                current, current_obj = best_neighbor, best_neighbor_obj
                idx = 0  # 개선 시 첫 이웃으로 복귀 — VND 핵심 규칙
            else:
                idx += 1
        return current
