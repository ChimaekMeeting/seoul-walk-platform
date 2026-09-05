"""
src/route_engine/waypoint_route_builder.py

임의의 경유지 순서(추상적인 정수 ID 나열)를 실제 노드열 기준 경로로 조립하는 공용 계층.

GRASP(engines/grasp_waypoint_common.py::construct_initial_route 등)과 Beam
(waypoint_beam.py::beam_search)은 각자 경유지 선택 알고리즘만 순수하게 유지하고,
실제 그래프 I/O(A* 구간 연결, PathUtils.prune_dead_ends)는 이 모듈에서만 담당한다
(2026-09-03, "Beam/GRASP 공용 조립 계층과 어댑터" 이슈).

이전에는 이 로직(BuildCycleRoute)이 engines/grasp_waypoint_common.py에 GRASP 전용으로
있어, Beam 결과를 같은 기준(노드열 stitching → prune_dead_ends → 거리·재통행비율
재계산)으로 재구성할 방법이 없었다. 이 모듈로 옮기면서 두 번째 인자를 GRASP 전용
_CostCache 객체 대신 평범한 콜러블(PathFinder)로 일반화했다 — waypoint_evaluation.py의
PathFunction과 같은 관례다.

engines/grasp_waypoint_common.py는 하위 호환을 위해 이 모듈의 Route/BuildCycleRoute
등을 그대로 재-export한다(기존 4개 GRASP 엔진 파일의 import는 바뀌지 않는다).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Optional

import networkx as nx

from src.route_engine.engines.path_utils import PathUtils

_LENGTH_ATTR = "length"  # 그래프 엣지 거리 속성명. engines/grasp_waypoint_common.py와 동일 기준.

PathFinder = Callable[[int, int], Optional[Sequence[int]]]
# 두 노드 사이의 실제 구간 노드열을 반환하는 콜러블. 도달 불가는 None.
# 반환 노드열은 항상 첫 인자에서 시작해 둘째 인자에서 끝나야 한다
# (waypoint_evaluation.py::PathFunction과 동일한 계약).


class MissingEdgeAttributeError(KeyError):
    """엣지에 필수 속성(예: length)이 없을 때 던진다. 0으로 조용히 대체하지 않는다 —
    그렇게 하면 모든 비용이 0으로 계산되는 오류가 숨겨질 수 있다."""


@dataclass
class Route:
    node_ids: list[int]
    waypoints: list[int]  # p1 다음 정류점부터 순서대로
    distance_m: float
    repeated_edge_ratio: float


def sum_edge_length(G: nx.Graph, path: list[int]) -> float:
    """항상 실제 물리적 거리(length)만 합산한다 — 탐색 비용 mode와 무관.
    Route.distance_m / 목표거리 비교는 항상 이 값을 쓴다."""
    total = 0.0
    for u, v in zip(path, path[1:]):
        edge = G[u][v]
        if _LENGTH_ATTR not in edge:
            raise MissingEdgeAttributeError(f"엣지에 '{_LENGTH_ATTR}' 속성이 없습니다: {edge!r}")
        total += edge[_LENGTH_ATTR]
    return total


def edge_overlap_ratio(G: nx.Graph, path: list[int]) -> float:
    """경로의 재통행 거리 비율(Beam·GRASP 공통 정의). 도로 엣지 하나가 두 번째 이후
    통행될 때만 그 구간의 실제 길이(length)를 repeated에 더한다(단순 재통행 횟수가 아니라
    거리 가중). 무방향 그래프이므로 (u,v)/(v,u)는 같은 구간으로 취급한다. 단순 왕복은
    정확히 0.5, 재통행이 전혀 없는 순환은 0이다."""
    if len(path) < 2:
        return 0.0
    seen: set[frozenset] = set()
    total = repeated = 0.0
    for u, v in zip(path, path[1:]):
        edge = G[u][v]
        if _LENGTH_ATTR not in edge:
            raise MissingEdgeAttributeError(f"엣지에 '{_LENGTH_ATTR}' 속성이 없습니다: {edge!r}")
        length = edge[_LENGTH_ATTR]
        key = frozenset((u, v))
        total += length
        if key in seen:
            repeated += length
        seen.add(key)
    return repeated / total if total else 0.0


def build_cycle_route(
    G: nx.Graph,
    path_finder: PathFinder,
    start_node: int,
    waypoints: Sequence[int],
) -> Optional[Route]:
    """start_node→waypoints[0]→...→waypoints[-1]→start_node 구간을 순서대로
    path_finder로 실제 연결한다. waypoints는 최소 1개 이상이어야 한다. 구간 중 하나라도
    실패(path_finder가 None 반환)하면 None(FAIL).

    distance_m은 반드시 반환된 실제 노드열의 엣지 길이 합산이며, 각 구간의 추정 비용을
    단순히 더한 값이 아니다.

    왕복 가지 제거(PathUtils.prune_dead_ends)를 여기서 미리 적용한다 — 그렇지 않으면
    "잠깐 나갔다가 그대로 되돌아오는" 구간이 raw 거리 합산에는 그대로 두 번 반영되어
    목표거리에 가까운 것처럼 보이지만, 실제로는 최종 표시 단계에서 똑같이 pruning되어
    거리가 크게 줄어드는 경로를 잘못 선택하게 된다. distance_m/repeated_edge_ratio를
    pruning 이후 기준으로 통일해 이 불일치를 없앤다.
    """
    if not waypoints:
        raise ValueError("waypoints는 최소 1개 이상이어야 합니다")

    stops = [start_node, *waypoints, start_node]
    node_ids: list[int] = []
    for a, b in zip(stops, stops[1:]):
        leg = path_finder(a, b)
        if leg is None:
            return None
        leg = list(leg)
        node_ids = node_ids + leg[1:] if node_ids else leg  # 구간 경계 중복 노드는 한 번만 남긴다

    if len(node_ids) < 2:
        return None

    pruned = PathUtils(G).prune_dead_ends(node_ids)
    if len(pruned) < 2:
        return None

    distance_m = sum_edge_length(G, pruned)
    repeated_edge_ratio = edge_overlap_ratio(G, pruned)
    return Route(
        node_ids=pruned,
        waypoints=list(waypoints),
        distance_m=distance_m,
        repeated_edge_ratio=repeated_edge_ratio,
    )


class DistancePathFinder:
    """distance 전용 A* PathFinder + 경로 캐시. GraspConfig/EdgeCost와 무관한 최소
    구현 — mode="distance"만 필요한 조립 계층(예: Beam)에서 GRASP 전용
    _CostCache(engines/grasp_waypoint_common.py) 없이 build_cycle_route/
    compute_route_geometry_metrics에 바로 넘길 수 있는 PathFinder를 만든다.

    astar_path()는 _CostCache.astar_path()와 동일한 캐싱 전략(양방향 키 정규화,
    실패도 캐시)과 astar_calls/cache_hits 카운터를 제공한다. _CostCache와 달리
    mode별 비용(EdgeCost) 합산 캐시(_cost_cache)는 두지 않는다 — 원본에서도 그
    값을 읽는 곳이 없었다.
    """

    def __init__(self, G: nx.Graph):
        self.G = G
        self._path_utils = PathUtils(G)
        self._path_cache: dict[tuple[int, int], Optional[list[int]]] = {}
        self.astar_calls = 0
        self.cache_hits = 0

    @staticmethod
    def _weight(u, v, edge_data) -> float:
        if _LENGTH_ATTR not in edge_data:
            raise MissingEdgeAttributeError(f"엣지에 '{_LENGTH_ATTR}' 속성이 없습니다: {edge_data!r}")
        return edge_data[_LENGTH_ATTR]

    @staticmethod
    def _key(a: int, b: int) -> tuple[int, int]:
        return (a, b) if a <= b else (b, a)

    def astar_path(self, a: int, b: int) -> Optional[list[int]]:
        """실패 시 None. 반환 노드열은 항상 a에서 시작해 b에서 끝난다."""
        key = self._key(a, b)
        if key in self._path_cache:
            self.cache_hits += 1
            cached = self._path_cache[key]
            if cached is None:
                return None
            return cached if cached[0] == a else list(reversed(cached))

        if a == b:
            path: Optional[list[int]] = [a]
        else:
            self.astar_calls += 1
            try:
                path = self._path_utils.astar_path(a, b, weight=self._weight)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                path = None

        self._path_cache[key] = path
        return path
