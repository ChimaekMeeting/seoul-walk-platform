"""
src/route_engine/engines/waypoint_local_search.py

WaypointReplacement 지역개선 — circular_grasp_waypoint_local.py::
CircularGraspWaypointLocalEngine._local_search()에 있던 로직을 독립 함수로 추출했다
("Beam/GRASP 구축·정제 조립 분리" 이슈, To-Do 1번). 개선이 없어질 때까지
WaypointReplacement 이웃에서 best-improvement를 반복 채택하는 순수 함수다 — 인자로
받은 route/pool_result만 쓰고, GRASP의 24회 랜덤 재시작 루프나 다른 인스턴스 상태를
가정하지 않는다. 동작은 원래 메서드와 완전히 동일하다.

cost_cache는 `.astar_path(a, b)`만 있으면 되는 덕타이핑 계약이다
(waypoint_route_builder.py::PathFinder와 동일한 관례 — waypoint_replacement_neighbors()
자신도 타입힌트는 GRASP 전용 _CostCache로 돼 있지만 실제로는 이 메서드 하나만 쓴다).
GRASP 4종은 _CostCache를, Beam(waypoint_engine_assembly.py::WaypointEngine)도 이제
같은 _CostCache를 쓴다.
"""

from __future__ import annotations

import networkx as nx

from src.route_engine.engines.grasp_waypoint_common import (
    GraspConfig,
    Route,
    RouteObjective,
    better,
    evaluate_route,
    waypoint_replacement_neighbors,
)
from src.route_engine.engines.waypoint_pool import WaypointPoolResult


def local_search(
    G: nx.Graph,
    cost_cache,
    pool_result: WaypointPoolResult,
    start_node: int,
    route: Route,
    target_m: float,
    cfg: GraspConfig,
) -> tuple[Route, RouteObjective]:
    """개선이 없어질 때까지 WaypointReplacement 이웃에서 best-improvement를 반복
    채택한다. 원래 circular_grasp_waypoint_local.py::CircularGraspWaypointLocalEngine.
    _local_search()에 있던 로직을 그대로 옮긴 것 — 동작은 바뀌지 않았다."""
    current = route
    current_obj = evaluate_route(current, target_m, target_m * cfg.distance_tolerance_ratio)
    improved = True
    while improved:
        improved = False
        best_neighbor, best_neighbor_obj = current, current_obj
        for neighbor in waypoint_replacement_neighbors(
            G, cost_cache, pool_result, start_node, current, target_m, cfg,
        ):
            neighbor_obj = evaluate_route(neighbor, target_m, target_m * cfg.distance_tolerance_ratio)
            if better(neighbor_obj, best_neighbor_obj):
                best_neighbor, best_neighbor_obj = neighbor, neighbor_obj
        if better(best_neighbor_obj, current_obj):
            current, current_obj = best_neighbor, best_neighbor_obj
            improved = True
    return current, current_obj
