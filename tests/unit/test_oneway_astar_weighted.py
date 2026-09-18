"""
tests/unit/test_oneway_astar_weighted.py
OnewayAstarEngine의 가중 비용 주입과 우회 상한 — #445 5단계

설계 결정(A): RouteService의 oneway_shortest는 cost_context를 넘기지 않아 물리
최단을 유지한다. 가중 비용은 WaypointComposerEngine이 leg 엔진으로 쓸 때만
주입된다. 그래서 "주입 없음 = 기존 동작 그대로"가 가장 중요한 회귀 기준이다.

검증 항목:
  - cost_context 없이 생성하면 length 기준 최단경로와 노드열이 같다
  - cost_context.enabled=False면 주입하지 않은 것과 동일하다
  - 가중 모드에서 안전 가중치를 올리면 안전한 우회로를 고른다
  - total_km은 탐색 비용이 아니라 실제 length 합이다
  - ALT를 붙인 가중 A*의 비용이 weighted Dijkstra와 같다(실제 엔진 경로에서)
  - visited_nodes 재방문 페널티가 가중 비용 위에 곱해진다
  - path_cost()는 주입 여부와 무관하게 거리를 돌려준다(벤치마크 계약)
  - 요청마다 전체 간선 lookup을 만들지 않는다
  - apply_detour_cap이 상한 초과 시 물리 최단으로 되돌린다
"""

import networkx as nx
import pytest

from src.route_engine.alt_runtime import attach_alt_heuristic, prepare_alt_heuristic
from src.route_engine.engines.oneway_astar import OnewayAstarEngine
from src.route_engine.engines.path_utils import _RETURN_REVISIT_PENALTY
from src.route_engine.scoring.detour_cap import apply_detour_cap, path_distance_m
from src.route_engine.scoring.scoring_engine import WeightedEdgeCost
from src.schema.route_schema import OnewayRouteInput

K = 1.0
LAMBDA = 0.5

# ── 그래프 ──────────────────────────────────────────────────────────────────
#
# 좌표를 위경도로 주고 length를 실제 Haversine 거리로 채운다. 그래야 엔진의 기본
# Haversine 휴리스틱과 ALT 둘 다 admissible해져서 실제 서비스 경로와 같은 조건이 된다.
#
#   S ── A ── B ── T      직선(짧지만 위험)
#   └─ C ── D ─┘          우회(길지만 안전)

# alt_runtime이 노드 ID를 int로 변환하므로 정수 ID를 쓴다.
S, A, B, T, C, D = 0, 1, 2, 3, 4, 5

_POS = {
    S: (37.5000, 127.0000),
    A: (37.5000, 127.0020),
    B: (37.5000, 127.0040),
    T: (37.5000, 127.0060),
    C: (37.5020, 127.0020),
    D: (37.5020, 127.0040),
}
_DIRECT = [S, A, B, T]
_DETOUR = [S, C, D, T]


def _haversine_m(a: int, b: int) -> float:
    from src.route_engine.engines.path_utils import PathUtils

    (lat1, lon1), (lat2, lon2) = _POS[a], _POS[b]
    return PathUtils._haversine_m(lat1, lon1, lat2, lon2)


def make_graph(direct=(0.0, 1.0), detour=(1.0, 0.0), slopes=(1.0, 1.0)) -> nx.Graph:
    """direct/detour = (safety_score, accident_score)."""
    G = nx.Graph()
    for node, (lat, lon) in _POS.items():
        G.add_node(node, lat=lat, lon=lon, x=lon, y=lat)
    for path, (safety, accident), slope in (
        (_DIRECT, direct, slopes[0]),
        (_DETOUR, detour, slopes[1]),
    ):
        for u, v in zip(path, path[1:]):
            G.add_edge(
                u, v,
                length=_haversine_m(u, v),
                safety_score=safety,
                accident_score=accident,
                slope_score=slope,
            )
    return G


def make_engine(G, cost_context=None, visited_nodes=None) -> OnewayAstarEngine:
    inp = OnewayRouteInput(
        start_lat=_POS[S][0], start_lon=_POS[S][1],
        end_lat=_POS[T][0], end_lon=_POS[T][1],
        target_km=1.0,
    )
    return OnewayAstarEngine(
        inp, G, cost_context=cost_context, visited_nodes=visited_nodes,
    )


def make_context(alpha=0.0, beta=0.0, **kwargs) -> WeightedEdgeCost:
    kwargs.setdefault("accident_ratio", LAMBDA)
    kwargs.setdefault("weight_limit", K)
    return WeightedEdgeCost(alpha, beta, **kwargs)


# ── 주입 없음 = 기존 동작 ───────────────────────────────────────────────────


def test_without_context_matches_plain_shortest_path():
    G = make_graph()
    engine = make_engine(G)

    assert engine.find_path(S, T) == [nx.shortest_path(G, S, T, weight="length")]
    assert engine.cost_context is None


def test_disabled_context_behaves_like_no_context():
    """커버리지 게이트가 끈 CostContext는 주입하지 않은 것과 같아야 한다."""
    G = make_graph()
    disabled = make_context(0.9, 0.0, enabled=False)
    engine = make_engine(G, cost_context=disabled)

    assert engine.cost_context is None
    assert engine.find_path(S, T) == [_DIRECT]


def test_zero_weight_context_picks_the_physical_shortest():
    G = make_graph()
    engine = make_engine(G, cost_context=make_context(0.0, 0.0))

    assert engine.find_path(S, T) == [_DIRECT]


# ── 가중 탐색 ───────────────────────────────────────────────────────────────


def test_high_safety_weight_switches_to_the_safe_detour():
    G = make_graph()
    engine = make_engine(G, cost_context=make_context(0.9, 0.0))

    assert engine.find_path(S, T) == [_DETOUR]


def test_high_comfort_weight_switches_to_the_flat_detour():
    G = make_graph(direct=(1.0, 0.0), detour=(1.0, 0.0), slopes=(0.0, 1.0))
    engine = make_engine(G, cost_context=make_context(0.0, 0.9))

    assert engine.find_path(S, T) == [_DETOUR]


def test_total_km_is_real_distance_not_search_cost():
    G = make_graph()
    engine = make_engine(G, cost_context=make_context(0.9, 0.0))
    response = engine.run()[0]

    expected_km = round(path_distance_m(G, _DETOUR) / 1000, 2)
    assert engine.last_path_nodes == _DETOUR
    assert response.total_km == expected_km


def test_weighted_astar_cost_equals_weighted_dijkstra():
    """엔진이 실제로 쓰는 경로에서 ALT/Haversine A*가 최적성을 유지하는지 확인한다."""
    G = make_graph()
    context = make_context(0.6, 0.3)
    engine = make_engine(G, cost_context=context)

    astar_cost = engine.weighted_path_cost(engine.find_path(S, T)[0])
    dijkstra_cost = nx.dijkstra_path_length(G, S, T, weight=context.weight)

    assert astar_cost == pytest.approx(dijkstra_cost)


def test_weighted_astar_with_alt_matches_dijkstra():
    G = make_graph()
    heuristic, info = prepare_alt_heuristic(G, enabled=True, method="planar", k=4, seed=0)
    attach_alt_heuristic(G, heuristic, info)

    context = make_context(0.6, 0.3)
    engine = make_engine(G, cost_context=context)
    assert engine.heuristic_name.startswith("alt_")

    astar_cost = engine.weighted_path_cost(engine.find_path(S, T)[0])

    assert astar_cost == pytest.approx(
        nx.dijkstra_path_length(G, S, T, weight=context.weight)
    )


def test_revisit_penalty_multiplies_the_weighted_cost():
    """visited_nodes 페널티는 가중 비용을 대체하지 않고 그 위에 곱해져야 한다.
    (배수 >= 1이므로 ALT admissibility도 유지된다)"""
    G = make_graph()
    context = make_context(0.5, 0.0)
    engine = make_engine(G, cost_context=context, visited_nodes={A})

    weight = engine._build_search_weight(T)
    base = context.weight(S, A, G[S][A])

    assert weight(S, A, G[S][A]) == pytest.approx(base * _RETURN_REVISIT_PENALTY)
    assert weight(B, T, G[B][T]) == pytest.approx(
        context.weight(B, T, G[B][T])
    )  # 도착지는 페널티 제외


# ── 벤치마크 계약 / 성능 ────────────────────────────────────────────────────


def test_path_cost_is_distance_even_in_weighted_mode():
    G = make_graph()
    engine = make_engine(G, cost_context=make_context(0.9, 0.0))

    # 안전한 우회로는 페널티가 0이라 두 값이 같고,
    assert engine.path_cost(_DETOUR) == pytest.approx(path_distance_m(G, _DETOUR))
    assert engine.weighted_path_cost(_DETOUR) == pytest.approx(engine.path_cost(_DETOUR))

    # 위험한 직선 구간에서는 가중 비용만 커진다 — path_cost는 거리 그대로여야 한다.
    assert engine.path_cost(_DIRECT) == pytest.approx(path_distance_m(G, _DIRECT))
    assert engine.weighted_path_cost(_DIRECT) > engine.path_cost(_DIRECT)


def test_distance_weight_matches_the_previous_lookup_contract():
    """_make_distance_weight가 compute_distance_only_lookup과 같은 값을 내는지 고정한다."""
    weight = OnewayAstarEngine._make_distance_weight()

    assert weight(0, 1, {"length": 120.0}) == 120.0
    # scoring_engine._build_feature_cache의 max(1.0, length)·기본값 1.0과 동일해야 한다
    assert weight(0, 1, {"length": 0.098}) == 1.0
    assert weight(0, 1, {}) == 1.0
    assert weight(0, 1, {"length": None}) == 1.0


def test_engine_never_calls_the_full_edge_lookup(monkeypatch):
    """요청마다 2*E 크기 dict를 만들던 병목이 사라졌는지 고정한다.

    속성이 비어 있는지 보는 것으로는 부족하다(대입만 안 했을 수도 있다). 아예
    compute_distance_only_lookup이 호출되면 실패하도록 막고 run()이 성공하는지 본다.
    """
    import src.route_engine.scoring.scoring_engine as scoring_engine

    def _boom(*args, **kwargs):
        raise AssertionError("요청 경로에서 전체 간선 lookup을 만들면 안 된다")

    monkeypatch.setattr(scoring_engine, "compute_distance_only_lookup", _boom)

    G = make_graph()
    engine = make_engine(G)
    response = engine.run()[0]

    assert response.total_km > 0
    assert engine.last_path_nodes == _DIRECT


# ── 우회 상한 ───────────────────────────────────────────────────────────────


def test_detour_within_cap_is_kept():
    G = make_graph()
    decision = apply_detour_cap(G, _DETOUR, _DIRECT, max_ratio=1.0)

    assert decision.capped is False
    assert decision.path == _DETOUR


def test_detour_over_cap_falls_back_to_physical_shortest():
    G = make_graph()
    decision = apply_detour_cap(G, _DETOUR, _DIRECT, max_ratio=0.01)

    assert decision.capped is True
    assert decision.path == _DIRECT
    assert decision.detour_ratio > 0.01


def test_identical_paths_are_never_capped():
    G = make_graph()
    decision = apply_detour_cap(G, _DIRECT, _DIRECT, max_ratio=0.0)

    assert decision.capped is False
    assert decision.detour_ratio == pytest.approx(0.0)


def test_missing_physical_path_keeps_the_weighted_one():
    G = make_graph()
    decision = apply_detour_cap(G, _DETOUR, None, max_ratio=0.0)

    assert decision.capped is False
    assert decision.path == _DETOUR


def test_negative_cap_is_rejected():
    with pytest.raises(ValueError, match="max_ratio"):
        apply_detour_cap(make_graph(), _DETOUR, _DIRECT, max_ratio=-0.1)


def test_detour_ratio_reports_the_actual_increase():
    G = make_graph()
    decision = apply_detour_cap(G, _DETOUR, _DIRECT, max_ratio=1.0)

    expected = path_distance_m(G, _DETOUR) / path_distance_m(G, _DIRECT) - 1.0
    assert decision.detour_ratio == pytest.approx(expected)
