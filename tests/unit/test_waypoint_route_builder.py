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
    Route,
    build_cycle_route,
    surviving_waypoints,
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


# ── 실효 경유지(pruning 이후 실제로 지난 경유지) ─────────────────────────
#
# build_cycle_route는 왕복 가지를 prune_dead_ends로 걷어내는데, 그 가지가 곧 어떤 경유지로
# 들어갔다 나오는 구간이면 경유지 노드 자체가 node_ids에서 사라진다. 그런데도 waypoints는
# 선언값 그대로 남아, "경유지 N개를 지난다"고 기록하면서 실제로는 그보다 적게 지나는
# Route가 정상 해로 채택됐다(2026-09-09 버그픽스).

def test_surviving_waypoints_keeps_requested_order_and_drops_absent_nodes():
    assert surviving_waypoints([1, 2, 3, 2, 1], [3, 2]) == [3, 2]  # 요청 순서 유지(경로 등장 순서 아님)
    assert surviving_waypoints([1, 2, 1], [2, 9]) == [2]
    assert surviving_waypoints([1], [7, 8]) == []


def test_route_fills_effective_waypoints_from_node_ids_by_default():
    """effective_waypoints를 안 넘기고 만든 Route도 __post_init__이 값을 채운다 —
    기존 Route 생성부가 인자 추가 없이 올바른 값을 갖게 하기 위한 계약이다."""
    route = Route(node_ids=[1, 2, 3, 2, 1], waypoints=[2, 3], distance_m=100.0, repeated_edge_ratio=0.0)
    assert route.effective_waypoints == [2, 3]
    assert route.effective_waypoint_count == 2


def test_build_cycle_route_reports_waypoint_erased_by_pruning(grid_graph):
    """막다른 가지 끝에 있는 경유지는 prune_dead_ends로 node_ids에서 사라지지만,
    waypoints는 선언값 그대로 남고 effective_waypoints만 줄어든다(탐색 입력은 보존,
    관측값만 정정)."""
    dead_end = 999
    anchor = _node_id(0, 0)
    lat, lon = _coords(0, 0)
    grid_graph.add_node(dead_end, lat=lat + _LAT_STEP / 4, lon=lon)
    grid_graph.add_edge(anchor, dead_end, length=40.0)  # 이 노드로 들어가는 길은 이 엣지 하나뿐

    finder = DistancePathFinder(grid_graph)
    start, far = _node_id(2, 2), _node_id(4, 4)

    route = build_cycle_route(grid_graph, finder.astar_path, start, [dead_end, far])
    assert route is not None
    assert route.waypoints == [dead_end, far]  # 선언값은 그대로 — 탐색 입력이라 건드리지 않는다
    assert dead_end not in route.node_ids  # 왕복 가지째 잘려나감
    assert dead_end not in route.effective_waypoints
    assert route.effective_waypoint_count < len(route.waypoints)  # 선언 N보다 실제로 적게 지난다
    # 실효 경유지는 언제나 "선언한 경유지 중 node_ids에 남아 있는 것"이다.
    assert route.effective_waypoints == [w for w in route.waypoints if w in set(route.node_ids)]


def test_geometry_metrics_expose_effective_waypoint_count(grid_graph):
    """CSV·로그가 읽는 진단 지표까지 실효 경유지 수가 전달되는지 확인한다."""
    finder = DistancePathFinder(grid_graph)
    start, p2, p3 = _node_id(0, 0), _node_id(0, 2), _node_id(2, 2)

    route = build_cycle_route(grid_graph, finder.astar_path, start, [p2, p3])
    assert route is not None

    metrics = compute_route_geometry_metrics(grid_graph, finder.astar_path, start, route, target_m=1000.0)
    assert metrics.effective_waypoint_count == route.effective_waypoint_count
    assert compute_route_geometry_metrics(
        grid_graph, finder.astar_path, start, None, target_m=1000.0
    ).effective_waypoint_count is None


def test_prune_diagnostics_attribute_lost_waypoints_to_branch_type(grid_graph):
    """사라진 경유지가 "재통행 있는 구간"과 "재통행 0인 구간" 중 어디에 휩쓸렸는지
    구분해 세는지 확인한다 — 겹침 기준으로 바꿨을 때 몇 개가 살아나는지를 이 값으로
    판단하므로, 두 유형을 섞으면 기준 전환의 기대 효과를 잘못 읽게 된다."""
    dead_end = 999
    anchor = _node_id(0, 0)
    lat, lon = _coords(0, 0)
    grid_graph.add_node(dead_end, lat=lat + _LAT_STEP / 4, lon=lon)
    grid_graph.add_edge(anchor, dead_end, length=40.0)

    finder = DistancePathFinder(grid_graph)
    start, far = _node_id(2, 2), _node_id(4, 4)
    route = build_cycle_route(grid_graph, finder.astar_path, start, [dead_end, far])
    assert route is not None

    metrics = compute_route_geometry_metrics(
        grid_graph, finder.astar_path, start, route, target_m=1000.0
    )
    pd = metrics.prune_diagnostics
    assert pd is not None
    assert pd.branch_count > 0
    # 곁가지·되짚기로 사라진 경유지이므로 재통행 있는 구간 쪽으로 귀속돼야 한다.
    assert pd.waypoints_lost_repeated > 0
    lost_total = pd.waypoints_lost_clean + pd.waypoints_lost_repeated
    assert lost_total == len(route.waypoints) - route.effective_waypoint_count
    assert pd.clean_branch_count <= pd.branch_count
    assert pd.clean_branch_length_m <= pd.branch_length_m
