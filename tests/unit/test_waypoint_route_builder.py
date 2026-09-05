"""
tests/unit/test_waypoint_route_builder.py

waypoint_route_builder.py::DistancePathFinder 단위 테스트. GraspConfig/EdgeCost와
무관한 distance 전용 A* PathFinder + 캐시 구현이 _CostCache.astar_path와 동등하게
동작하는지, 그리고 compute_route_geometry_metrics가 이 콜러블만으로도(GRASP
_CostCache 없이) 동작하는지 검증한다(refactor/394 "Beam 경유지 조합용
BasePathSolver 래퍼" 이슈).
"""

import networkx as nx
import pytest

from src.route_engine.engines.grasp_waypoint_common import compute_route_geometry_metrics
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.waypoint_route_builder import (
    DistancePathFinder,
    MissingEdgeAttributeError,
    build_cycle_route,
)

_LAT_STEP = 0.0015
_LON_STEP = 0.0018
_ORIGIN_LAT = 37.5000
_ORIGIN_LON = 127.0000


def _node_id(row: int, col: int) -> int:
    return row * 5 + col + 1


def _coords(row: int, col: int) -> tuple[float, float]:
    return _ORIGIN_LAT + row * _LAT_STEP, _ORIGIN_LON + col * _LON_STEP


@pytest.fixture
def grid_graph() -> nx.Graph:
    """5x5 격자 그래프(실제 위경도 간격 부여). 모든 엣지 length는 두 끝점의 실제
    Haversine 거리로 설정해 A*가 의미 있게 동작하게 한다."""
    G = nx.Graph()
    for row in range(5):
        for col in range(5):
            lat, lon = _coords(row, col)
            G.add_node(_node_id(row, col), lat=lat, lon=lon)

    for row in range(5):
        for col in range(5):
            n = _node_id(row, col)
            if col < 4:
                e = _node_id(row, col + 1)
                lat1, lon1 = _coords(row, col)
                lat2, lon2 = _coords(row, col + 1)
                G.add_edge(n, e, length=PathUtils._haversine_m(lat1, lon1, lat2, lon2))
            if row < 4:
                s = _node_id(row + 1, col)
                lat1, lon1 = _coords(row, col)
                lat2, lon2 = _coords(row + 1, col)
                G.add_edge(n, s, length=PathUtils._haversine_m(lat1, lon1, lat2, lon2))
    return G


def test_astar_path_caches_and_counts_calls(grid_graph):
    finder = DistancePathFinder(grid_graph)
    a, b = _node_id(0, 0), _node_id(2, 2)

    first = finder.astar_path(a, b)
    assert first is not None
    assert finder.astar_calls == 1
    assert finder.cache_hits == 0

    second = finder.astar_path(a, b)
    assert second == first
    assert finder.astar_calls == 1
    assert finder.cache_hits == 1


def test_astar_path_reversed_query_reuses_cache(grid_graph):
    finder = DistancePathFinder(grid_graph)
    a, b = _node_id(0, 0), _node_id(2, 2)

    forward = finder.astar_path(a, b)
    backward = finder.astar_path(b, a)

    assert finder.astar_calls == 1
    assert finder.cache_hits == 1
    assert backward == list(reversed(forward))


def test_astar_path_same_node_returns_single_node_without_astar_call(grid_graph):
    finder = DistancePathFinder(grid_graph)
    a = _node_id(1, 1)
    assert finder.astar_path(a, a) == [a]
    assert finder.astar_calls == 0


def test_astar_path_unreachable_returns_none_and_is_cached(grid_graph):
    G = grid_graph.copy()
    G.add_node(999, lat=_ORIGIN_LAT + 10, lon=_ORIGIN_LON + 10)  # 고립 노드
    finder = DistancePathFinder(G)
    a = _node_id(0, 0)

    assert finder.astar_path(a, 999) is None
    assert finder.astar_calls == 1
    assert finder.astar_path(a, 999) is None
    assert finder.astar_calls == 1  # 실패도 캐시되어 재탐색하지 않음
    assert finder.cache_hits == 1


def test_astar_path_missing_length_attribute_raises(grid_graph):
    G = grid_graph.copy()
    a, b = _node_id(0, 0), _node_id(0, 1)
    del G[a][b]["length"]
    finder = DistancePathFinder(G)
    with pytest.raises(MissingEdgeAttributeError):
        finder.astar_path(a, _node_id(2, 2))


def test_distance_path_finder_works_as_build_cycle_route_path_finder(grid_graph):
    """GraspConfig/EdgeCost 없이도 build_cycle_route와 바로 조합되는지 확인한다
    (_CostCache.astar_path를 넘기던 자리를 그대로 대체할 수 있어야 한다)."""
    finder = DistancePathFinder(grid_graph)
    start, p2, p3 = _node_id(0, 0), _node_id(0, 2), _node_id(2, 2)

    route = build_cycle_route(grid_graph, finder.astar_path, start, [p2, p3])
    assert route is not None
    assert route.node_ids[0] == start
    assert route.node_ids[-1] == start


def test_compute_route_geometry_metrics_accepts_distance_path_finder(grid_graph):
    """일반화 이후 compute_route_geometry_metrics가 GRASP _CostCache 없이 임의의
    PathFinder 콜러블만으로 동작하는지 확인한다."""
    finder = DistancePathFinder(grid_graph)
    start, p2, p3 = _node_id(0, 0), _node_id(0, 2), _node_id(2, 2)

    route = build_cycle_route(grid_graph, finder.astar_path, start, [p2, p3])
    assert route is not None

    metrics = compute_route_geometry_metrics(grid_graph, finder.astar_path, start, route, target_m=1000.0)
    assert metrics.repeated_edge_ratio == route.repeated_edge_ratio
    assert metrics.segment_lengths_m is not None
