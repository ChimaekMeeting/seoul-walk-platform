"""
src/route_engine/waypoint_pool_beam_adapter.py

GRASP이 만든 WaypointPoolResult(engines/waypoint_pool.py)를 Beam(waypoint_beam.py)의
입력 형식(WaypointCandidate 목록·CostFunction)으로 변환하는 어댑터(2026-09-03,
"Beam/GRASP 공용 조립 계층과 어댑터" 이슈). 두 엔진이 같은 후보 풀을 쓰게 하는 게
목적이며, 그 자체로 경로를 만들지는 않는다 — 조립은 waypoint_route_builder.py가
맡는다.
"""

from __future__ import annotations

from math import inf

import networkx as nx

from src.route_engine.engines.waypoint_pool import WaypointPoolResult
from src.route_engine.waypoint_types import CostFunction, WaypointCandidate


def waypoint_pool_to_beam_candidates(
    G: nx.Graph, pool_result: WaypointPoolResult
) -> list[WaypointCandidate]:
    """pool_result.pool_nodes를 beam_search가 요구하는 WaypointCandidate 목록으로
    변환한다. start_node(p1)는 pool_result에 애초에 포함되지 않는다(waypoint_pool.py
    참고) — beam_search는 candidates에 start_id/end_id가 없어도 동작한다."""
    return [
        WaypointCandidate(node_id=node_id, lat=G.nodes[node_id]["lat"], lon=G.nodes[node_id]["lon"])
        for node_id in pool_result.pool_nodes
    ]


def waypoint_pool_cost_function(pool_result: WaypointPoolResult, start_node: int, end_node=None) -> CostFunction:
    """pool_result.distance()/dist_from_p1을 beam_search가 요구하는 cost(a, b) 콜러블로
    감싼다. start_node는 pool_result의 풀 노드가 아니므로(p1 자신은 제외) dist_from_p1으로
    따로 처리한다 — grasp_waypoint_common.py::_rank_next_waypoint_candidates가 prev==p1일
    때 쓰는 것과 같은 분기다. r_max 밖이라 거리를 못 구하면 inf를 반환한다(beam_search의
    cost 계약과 동일).

    end_node(편도 지원, 2026-09-20, #498 확장): None이면(기본값) start_node만 특별
    취급하는 기존 동작과 동일하다. end_node가 주어지면(start_node와 다르면) 그 노드가
    관여하는 구간은 dist_from_p2로 처리한다 — waypoint_refinement.py::_alns_cost_fn과
    같은 방식. pool_result가 dist_from_p2를 갖지 않으면(WaypointPoolResultTwoPoint가
    아니면) AttributeError로 즉시 드러난다."""

    def cost(a: int, b: int) -> float:
        if a == b:
            return 0.0
        if a == start_node:
            distance = pool_result.dist_from_p1.get(b)
        elif b == start_node:
            distance = pool_result.dist_from_p1.get(a)
        elif end_node is not None and a == end_node:
            distance = pool_result.dist_from_p2.get(b)
        elif end_node is not None and b == end_node:
            distance = pool_result.dist_from_p2.get(a)
        else:
            distance = pool_result.distance(a, b)
        return distance if distance is not None else inf

    return cost
