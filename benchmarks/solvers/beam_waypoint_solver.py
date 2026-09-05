"""
benchmarks/solvers/beam_waypoint_solver.py

신세대 Beam(waypoint_beam.py::beam_search)을 GRASP-Waypoint 4종
(grasp_waypoint_solver.py)과 같은 조건·같은 CSV 스키마로 비교하기 위한
BasePathSolver 어댑터.

Beam은 GRASP과 달리 "경유지 선택" 하나만 순수 탐색하고, 실제 그래프 I/O(구간 A*
연결)는 하지 않는다(2026-09-03 "Beam/GRASP 공용 조립 계층" 리팩터). 그래서 이
solver가 다음 순서로 조각을 직접 엮는다:

  1) WaypointPoolGenerator.build_pool() — GRASP과 동일한 후보 풀(p1 기준 cutoff SSSP)
  2) waypoint_pool_beam_adapter.py — 위 풀을 beam_search가 요구하는
     candidates/cost 형태로 변환
  3) beam_search() — 추상적인 경유지 순서 조합만 beam_width개까지 탐색
  4) build_cycle_route() — 각 조합을 실제 A*로 연결(distance 전용
     DistancePathFinder — GraspConfig/EdgeCost와 무관, waypoint_route_builder.py)
  5) evaluate_route()/better() — GRASP과 동일한 사전식 비교로 beam_width개 조합 중
     최선 선택
  6) compute_route_geometry_metrics()/determine_selection_status() — GRASP과 완전히
     같은 함수로 CSV 필드(d12/d23/d31 등)를 채움

GRASP 전용 _CostCache(engines/grasp_waypoint_common.py)는 옮기지 않는다 — 이 solver는
mode="distance"만 쓰므로 DistancePathFinder로 충분하다.
"""

from typing import Optional

from benchmarks.solvers.base_solver import BasePathSolver
from src.route_engine.engines.grasp_waypoint_common import (
    RouteGeometryMetrics,
    SelectionStatus,
    _INFEASIBLE,
    better,
    compute_route_geometry_metrics,
    determine_selection_status,
    evaluate_route,
)
from src.route_engine.engines.waypoint_pool import WaypointPoolGenerator
from src.route_engine.waypoint_beam import beam_search
from src.route_engine.waypoint_pool_beam_adapter import (
    waypoint_pool_cost_function,
    waypoint_pool_to_beam_candidates,
)
from src.route_engine.waypoint_route_builder import DistancePathFinder, build_cycle_route

_DEFAULT_TARGET_KM = 3.0
_DEFAULT_SEED = 42
_DEFAULT_NUM_WAYPOINTS = 2  # GraspConfig.num_waypoints 기본값과 동일
_DEFAULT_BEAM_WIDTH = 8  # GraspConfig.rcl_size 기본값과 맞춘 "공정 비교" 기본값
_DEFAULT_DISTANCE_TOLERANCE_RATIO = 0.05  # GraspConfig.distance_tolerance_ratio 기본값과 동일
_DEFAULT_MIN_WAYPOINT_SEPARATION_RATIO = 0.20  # GraspConfig.min_waypoint_separation_ratio 기본값과 동일
_DEFAULT_PAIRWISE_CACHE_ROWS = 256  # GraspConfig.pairwise_cache_rows 기본값과 동일


def _segment_metrics_from_geometry(
    gm: Optional[RouteGeometryMetrics], status: Optional[str], min_separation_m: float,
) -> dict:
    """grasp_waypoint_solver.py::_segment_metrics()와 같은 키 구성을 만든다. GRASP은
    engine 객체에서 last_geometry_metrics/last_selection_status/config를 읽지만,
    Beam은 이 solver 안에서 직접 계산하므로 그 값들을 인자로 받는다."""

    def r(value, digits=4):
        return round(value, digits) if value is not None else None

    if gm is None:
        gm = RouteGeometryMetrics(None, None, None, None, None, False)

    segments = gm.segment_lengths_m
    angles = gm.waypoint_angle_diffs_deg

    return {
        "selection_status": status,
        "feasible": status == SelectionStatus.FEASIBLE,
        "segment_p1_p2_m": r(segments[0]) if segments else None,
        "segment_p2_p3_m": r(segments[1]) if segments and len(segments) > 1 else None,
        "segment_p3_p1_m": r(segments[-1]) if segments else None,
        "waypoint_separation_m": r(gm.waypoint_separation_m),
        "min_waypoint_separation_m": round(min_separation_m, 4),
        "repeated_edge_ratio": r(gm.repeated_edge_ratio, 4),
        "waypoint_angle_diff_deg": r(angles[0], 2) if angles else None,
        "segment_balance_ratio": r(gm.segment_balance_ratio, 4),
        "is_degenerate_loop": gm.is_degenerate_loop,
    }


class CircularBeamWaypointSolver(BasePathSolver):
    def __init__(self, name: str = "Beam-Waypoint", seed: int = _DEFAULT_SEED):
        super().__init__(name)
        self.seed = seed

    def solve(self, graph, start_node, target_node, params: dict) -> dict:
        target_km = params.get("target_km") or _DEFAULT_TARGET_KM
        target_m = target_km * 1000
        num_waypoints = params.get("num_waypoints", _DEFAULT_NUM_WAYPOINTS)
        beam_width = params.get("beam_width", _DEFAULT_BEAM_WIDTH)
        distance_tolerance_ratio = params.get("distance_tolerance_ratio", _DEFAULT_DISTANCE_TOLERANCE_RATIO)
        min_waypoint_separation_ratio = params.get(
            "min_waypoint_separation_ratio", _DEFAULT_MIN_WAYPOINT_SEPARATION_RATIO
        )
        pairwise_cache_rows = params.get("pairwise_cache_rows", _DEFAULT_PAIRWISE_CACHE_ROWS)
        min_separation_m = target_m * min_waypoint_separation_ratio

        path_finder = DistancePathFinder(graph)

        start_data = graph.nodes[start_node]
        pool_result = WaypointPoolGenerator(graph).build_pool(
            start_data.get("lat", 0.0), start_data.get("lon", 0.0), target_km,
            pairwise_cache_rows=pairwise_cache_rows,
        )

        if pool_result is None or len(pool_result.pool_nodes) < num_waypoints:
            # grasp-wp-* solver(_circular_engine_common.py::run_circular_engine_distance_only)와
            # 동일한 실패 규약 — 유효한 순환 경로를 못 만들면 여기서 raise해 벤치마크
            # 하네스가 status="failed" 행으로 처리하게 한다. cost=0.0짜리 가짜 "ok" 행을
            # 만들면 GRASP과 CSV 상에서 비교가 어긋난다(실측 회귀로 확인, 2026-09-05).
            raise ValueError("경로 생성 실패: 유효한 순환 경로를 찾지 못했습니다 (NO_PATH)")

        candidates = waypoint_pool_to_beam_candidates(graph, pool_result)
        cost = waypoint_pool_cost_function(pool_result, start_node)

        result = beam_search(
            candidates=candidates,
            cost=cost,
            start_id=start_node,
            end_id=start_node,
            target_m=target_m,
            waypoint_count=num_waypoints,
            beam_width=beam_width,
        )
        had_valid_waypoint_pair = bool(result.orders)

        best_route, best_obj = None, _INFEASIBLE
        for order in result.orders:
            route = build_cycle_route(graph, path_finder.astar_path, start_node, order.waypoint_ids)
            if route is None:
                continue
            obj = evaluate_route(route, target_m, target_m * distance_tolerance_ratio)
            if best_route is None or better(obj, best_obj):
                best_obj, best_route = obj, route

        if best_route is None:
            # 위와 동일한 실패 규약 — beam_search가 조합(들)은 찾았지만(had_valid_waypoint_pair)
            # 그중 어느 것도 실제 A* 연결·prune_dead_ends를 통과하지 못한 경우
            # (예: 두 후보가 사실상 같은 도로의 왕복이라 pruning으로 통째로 사라짐).
            raise ValueError("경로 생성 실패: 유효한 순환 경로를 찾지 못했습니다 (NO_PATH)")

        selection_status = determine_selection_status(best_route, best_obj, had_valid_waypoint_pair)
        geometry_metrics = compute_route_geometry_metrics(
            graph, path_finder.astar_path, start_node, best_route, target_m
        )

        return {
            "paths": [best_route.node_ids],
            "cost": best_route.distance_m,
            "overlap_ratio": 0.0,  # grasp-wp-* solver와 동일하게 0.0 고정 — 실측값은 repeated_edge_ratio에
            "astar_calls": path_finder.astar_calls,
            "cache_hits": path_finder.cache_hits,
            **_segment_metrics_from_geometry(geometry_metrics, selection_status, min_separation_m),
        }
