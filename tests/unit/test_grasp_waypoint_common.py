import networkx as nx
import pytest

from src.route_engine.alt_runtime import attach_alt_heuristic, prepare_alt_heuristic
from src.route_engine.engines.grasp_waypoint_common import EdgeCost, _CostCache, is_degenerate_loop_route
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.scoring.scoring_engine import WeightedEdgeCost


def test_simple_round_trip_now_caught_by_new_threshold():
    # 단순 왕복(새 정의 기준 repeated_edge_ratio=0.5)은 이전 0.50 임계값으로는
    # 놓쳤지만(0.5 > 0.50이 False), 새 0.35 임계값에서는 잡혀야 한다(0.5 > 0.35).
    assert is_degenerate_loop_route(0.5, 1000.0, 3000.0, 0.9) is True


def test_repeated_edge_ratio_boundary():
    assert is_degenerate_loop_route(0.35, None, 3000.0, None) is False   # 경계값 포함 안 됨
    assert is_degenerate_loop_route(0.351, None, 3000.0, None) is True


def test_waypoint_separation_boundary():
    target_m = 3000.0
    assert is_degenerate_loop_route(0.0, target_m * 0.20, target_m, None) is False
    assert is_degenerate_loop_route(0.0, target_m * 0.20 - 1, target_m, None) is True


def test_segment_balance_boundary():
    assert is_degenerate_loop_route(0.0, None, 3000.0, 0.25) is False
    assert is_degenerate_loop_route(0.0, None, 3000.0, 0.249) is True


def test_none_values_skip_their_condition():
    assert is_degenerate_loop_route(0.0, None, 3000.0, None) is False


# ── _CostCache.cost_context 주입(#462) ──────────────────────────────────────
#
#   S ── A ── B ── T      직선(짧지만 위험)
#   └─ C ── D ─┘          우회(길지만 안전)
#
# astar_path_avoiding_edges()(VNS shake 전용)는 다루지 않는다 — 운영 알고리즘이
# GRASP+ALNS로 확정되어 VNS는 대상이 아니다.

_S, _A, _B, _T, _C, _D = 0, 1, 2, 3, 4, 5

_POS = {
    _S: (37.5000, 127.0000),
    _A: (37.5000, 127.0020),
    _B: (37.5000, 127.0040),
    _T: (37.5000, 127.0060),
    _C: (37.5020, 127.0020),
    _D: (37.5020, 127.0040),
}
_DIRECT = [_S, _A, _B, _T]
_DETOUR = [_S, _C, _D, _T]


def _haversine_m(a: int, b: int) -> float:
    (lat1, lon1), (lat2, lon2) = _POS[a], _POS[b]
    return PathUtils._haversine_m(lat1, lon1, lat2, lon2)


def _make_graph(direct=(0.0, 1.0), detour=(1.0, 0.0)) -> nx.Graph:
    """direct/detour = (safety_score, accident_score)."""
    G = nx.Graph()
    for node, (lat, lon) in _POS.items():
        G.add_node(node, lat=lat, lon=lon)
    for path, (safety, accident) in ((_DIRECT, direct), (_DETOUR, detour)):
        for u, v in zip(path, path[1:]):
            G.add_edge(
                u, v,
                length=_haversine_m(u, v),
                safety_score=safety,
                accident_score=accident,
                slope_score=1.0,
            )
    return G


def _make_context(alpha=0.0, beta=0.0, **kwargs) -> WeightedEdgeCost:
    kwargs.setdefault("accident_ratio", 0.5)
    kwargs.setdefault("weight_limit", 1.0)
    return WeightedEdgeCost(alpha, beta, **kwargs)


def test_cost_cache_without_context_matches_plain_edge_cost():
    G = _make_graph()
    cache = _CostCache(G, mode="distance")

    assert cache.cost_context is None
    assert cache.astar_path(_S, _T) == _DIRECT
    assert cache.astar_path(_S, _T) == nx.shortest_path(G, _S, _T, weight="length")


def test_cost_cache_disabled_context_behaves_like_no_context():
    G = _make_graph()
    disabled = _make_context(0.9, 0.0, enabled=False)
    cache = _CostCache(G, mode="distance", cost_context=disabled)

    assert cache.cost_context is None
    assert cache.astar_path(_S, _T) == _DIRECT


def test_cost_cache_weight_falls_back_to_edge_cost_without_context():
    G = _make_graph()
    cache = _CostCache(G, mode="distance")
    edge_data = G[_S][_A]

    assert cache._weight(_S, _A, edge_data) == EdgeCost("distance", edge_data)


def test_cost_cache_high_safety_weight_switches_astar_to_the_detour():
    G = _make_graph()
    cache = _CostCache(G, mode="distance", cost_context=_make_context(0.9, 0.0))

    assert cache.astar_path(_S, _T) == _DETOUR


def test_cost_cache_weight_uses_cost_context_when_enabled():
    G = _make_graph()
    context = _make_context(0.9, 0.0)
    cache = _CostCache(G, mode="distance", cost_context=context)
    edge_data = G[_S][_A]

    assert cache._weight(_S, _A, edge_data) == pytest.approx(context.weight(_S, _A, edge_data))


# ── 구간 연결 A*의 ALT 휴리스틱(#465) ───────────────────────────────────────
#
# 순환 경로의 구간 연결은 _CostCache.astar_path() → PathUtils.astar_path()를 타므로,
# 그래프에 ALT가 부착돼 있으면 최단거리 A*와 같은 휴리스틱을 쓴다. ALT 거리표는
# length 기준이고 가중 비용은 cost >= length이므로 하한이 그대로 admissible하다
# (scoring_engine.py의 WeightedEdgeCost 주석 참고). 아래 두 테스트는 그 결과로
# 나온 경로가 실제로 최적인지를 dijkstra와 대조해 고정한다.


def _attach_alt(G: nx.Graph):
    heuristic, info = prepare_alt_heuristic(G, enabled=True, method="planar", k=4, seed=0)
    attach_alt_heuristic(G, heuristic, info)
    return heuristic


def _weighted_cost(G: nx.Graph, path, context: WeightedEdgeCost) -> float:
    return sum(context.weight(u, v, G[u][v]) for u, v in zip(path, path[1:]))


def test_cost_cache_uses_the_attached_alt_heuristic():
    G = _make_graph()
    attached = _attach_alt(G)
    assert attached is not None  # 부착 자체가 실패하면 이 테스트는 의미가 없다

    cache = _CostCache(G, mode="distance")

    assert cache._path_utils._search_heuristic(1.0) is attached


def test_cost_cache_with_alt_and_weighted_cost_matches_dijkstra():
    G = _make_graph()
    _attach_alt(G)
    context = _make_context(0.6, 0.3)
    cache = _CostCache(G, mode="distance", cost_context=context)

    path = cache.astar_path(_S, _T)

    assert _weighted_cost(G, path, context) == pytest.approx(
        nx.dijkstra_path_length(G, _S, _T, weight=context.weight)
    )


def test_cost_cache_with_alt_matches_dijkstra_on_distance():
    G = _make_graph()
    _attach_alt(G)
    cache = _CostCache(G, mode="distance")

    assert cache.astar_path(_S, _T) == nx.shortest_path(G, _S, _T, weight="length")
