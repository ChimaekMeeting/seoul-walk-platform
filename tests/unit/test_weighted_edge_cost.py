"""
tests/unit/test_weighted_edge_cost.py
WeightedEdgeCost(안전·편안 가중 탐색 비용) 단위 테스트 — #445 1단계

가장 중요한 검증 항목은 첫 번째다. 이 불변식이 깨지면 기동 때 length로 만들어 둔
ALT Planar 거리표를 가중 탐색에 재사용할 수 없게 되고, A*가 최적이 아닌 경로를
반환할 수 있다.

검증 항목:
  - [불변식] 모든 유효 입력에서 weight() >= length
  - alpha=beta=0이면 비용이 length와 정확히 같다(거리 전용 회귀)
  - unsafe는 안전시설 부족과 사고위험을 accident_ratio로 결합한다
  - discomfort는 slope_score가 클수록(평탄할수록) 작아진다
  - 경계값(alpha/beta 음수, 합 상한 초과, accident_ratio 범위, weight_limit)은
    조용히 보정하지 않고 예외로 거부한다
  - 점수가 0~1을 벗어나면 엣지 정보를 담아 예외를 던진다
  - length 누락은 MissingEdgeAttributeError
  - 커버리지 미달이면 가중 모드를 끄고 거리 전용으로 동작하며 경고를 1회 남긴다
  - 커버리지 충족 시 남은 NULL은 중앙값으로 대체하고 횟수를 센다
  - weight()는 입력 edge_data를 변경하지 않는다
  - normalize_preference_weights는 선호도를 alpha+beta <= k로 변환한다
  - [통합] 합성 그래프에서 ALT식 휴리스틱 A*와 Dijkstra의 최소 비용이 같고,
    안전 가중치를 올리면 실제로 안전한 우회로로 선택이 바뀐다
"""

import logging
import math

import networkx as nx
import pytest

from src.route_engine.scoring.scoring_engine import (
    ACCIDENT_ATTR,
    SAFETY_ATTR,
    SLOPE_ATTR,
    CoverageReport,
    WeightedEdgeCost,
    normalize_preference_weights,
    path_feature_averages,
    precompute_scoring_features,
)
from src.route_engine.waypoint_route_builder import MissingEdgeAttributeError

# ── 헬퍼 ────────────────────────────────────────────────────────────────────

K = 1.0          # weight_limit 기본값(테스트 전용, 코드 기본값 아님)
LAMBDA = 0.5     # accident_ratio 기본값(테스트 전용, 코드 기본값 아님)


def make_edge(length=100.0, safety=1.0, accident=0.0, slope=1.0, **extra) -> dict:
    """페널티가 0인 엣지가 기본값 — 즉 기본 엣지의 비용은 항상 length와 같다."""
    return {
        "length": length,
        SAFETY_ATTR: safety,
        ACCIDENT_ATTR: accident,
        SLOPE_ATTR: slope,
        **extra,
    }


def make_cost(alpha=0.0, beta=0.0, **kwargs) -> WeightedEdgeCost:
    kwargs.setdefault("accident_ratio", LAMBDA)
    kwargs.setdefault("weight_limit", K)
    return WeightedEdgeCost(alpha, beta, **kwargs)


def make_graph(edges: list[tuple[int, int, dict]]) -> nx.Graph:
    G = nx.Graph()
    for u, v, data in edges:
        G.add_edge(u, v, **data)
    return G


# ── 불변식: weight() >= length ──────────────────────────────────────────────


@pytest.mark.parametrize("alpha,beta", [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (0.5, 0.5), (0.3, 0.2)])
@pytest.mark.parametrize("safety", [0.0, 0.5, 1.0])
@pytest.mark.parametrize("accident", [0.0, 0.5, 1.0])
@pytest.mark.parametrize("slope", [0.0, 0.5, 1.0])
def test_weight_is_never_below_length(alpha, beta, safety, accident, slope):
    """ALT 재사용의 근거. 어떤 가중치·점수 조합에서도 비용이 거리보다 작아지면 안 된다."""
    cost = make_cost(alpha, beta)
    edge = make_edge(safety=safety, accident=accident, slope=slope)

    assert cost.weight(0, 1, edge) >= edge["length"]


def test_zero_weights_equal_plain_length():
    """alpha=beta=0이면 페널티가 아무리 커도 비용은 정확히 거리다(거리 전용 회귀)."""
    cost = make_cost(0.0, 0.0)
    edge = make_edge(length=250.0, safety=0.0, accident=1.0, slope=0.0)

    assert cost.weight(0, 1, edge) == 250.0


# ── unsafe / discomfort ─────────────────────────────────────────────────────


def test_unsafe_uses_only_safety_deficit_when_ratio_is_one():
    cost = make_cost(accident_ratio=1.0)

    assert cost.unsafe(make_edge(safety=0.25, accident=1.0)) == pytest.approx(0.75)


def test_unsafe_uses_only_accident_when_ratio_is_zero():
    cost = make_cost(accident_ratio=0.0)

    assert cost.unsafe(make_edge(safety=0.0, accident=0.4)) == pytest.approx(0.4)


def test_accident_ratio_actually_moves_the_result():
    """lambda가 형식적 인자가 아니라 실제로 결합 비율로 동작하는지 확인한다."""
    edge = make_edge(safety=1.0, accident=1.0)  # 시설은 충분하지만 사고는 잦은 도로

    low = make_cost(accident_ratio=0.3).unsafe(edge)
    high = make_cost(accident_ratio=0.7).unsafe(edge)

    assert low == pytest.approx(0.7)
    assert high == pytest.approx(0.3)
    assert low > high


def test_discomfort_is_inverse_of_slope_score():
    cost = make_cost()

    assert cost.discomfort(make_edge(slope=1.0)) == pytest.approx(0.0)
    assert cost.discomfort(make_edge(slope=0.0)) == pytest.approx(1.0)
    assert cost.discomfort(make_edge(slope=0.25)) == pytest.approx(0.75)


def test_read_only_score_lookup_does_not_increment_median_substitutions():
    """벤치마크 사후 측정은 탐색 중 발생한 결측 대체 진단을 바꾸지 않는다."""
    medians = {SAFETY_ATTR: 0.5, ACCIDENT_ATTR: 0.5, SLOPE_ATTR: 0.5}
    cost = make_cost(medians=medians)
    edge = make_edge(safety=None, accident=None, slope=None)

    cost.unsafe(edge, track_substitutions=False)
    cost.discomfort(edge, track_substitutions=False)

    assert cost.median_substitutions == 0


def test_cost_formula_matches_specification():
    cost = make_cost(alpha=0.4, beta=0.2, accident_ratio=0.5)
    edge = make_edge(length=100.0, safety=0.0, accident=1.0, slope=0.0)

    # unsafe = 0.5*(1-0) + 0.5*1 = 1.0, discomfort = 1-0 = 1.0
    assert cost.weight(0, 1, edge) == pytest.approx(100.0 * (1 + 0.4 * 1.0 + 0.2 * 1.0))


# ── 경계값 거부 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("alpha,beta", [(-0.1, 0.0), (0.0, -0.1)])
def test_negative_coefficients_are_rejected(alpha, beta):
    with pytest.raises(ValueError):
        make_cost(alpha, beta)


def test_sum_over_weight_limit_is_rejected():
    with pytest.raises(ValueError, match="상한"):
        make_cost(0.7, 0.4, weight_limit=1.0)


@pytest.mark.parametrize("ratio", [-0.01, 1.01])
def test_accident_ratio_out_of_range_is_rejected(ratio):
    with pytest.raises(ValueError, match="accident_ratio"):
        make_cost(accident_ratio=ratio)


@pytest.mark.parametrize("limit", [0.0, -1.0])
def test_non_positive_weight_limit_is_rejected(limit):
    with pytest.raises(ValueError, match="weight_limit"):
        make_cost(weight_limit=limit)


# ── 잘못된 엣지 데이터 ──────────────────────────────────────────────────────


@pytest.mark.parametrize("attr", [SAFETY_ATTR, ACCIDENT_ATTR, SLOPE_ATTR])
def test_score_out_of_range_raises_with_edge_identity(attr):
    """조용히 clamp하면 데이터 품질 문제가 숨는다 — 엣지 정보를 담아 던진다."""
    kwarg = {SAFETY_ATTR: "safety", ACCIDENT_ATTR: "accident", SLOPE_ATTR: "slope"}[attr]
    cost = make_cost(0.5, 0.5)
    edge = make_edge(**{kwarg: 1.5})

    with pytest.raises(ValueError) as excinfo:
        cost.weight(0, 1, edge)

    assert attr in str(excinfo.value)


def test_missing_length_raises_missing_edge_attribute_error():
    cost = make_cost(0.5, 0.0)
    edge = make_edge()
    del edge["length"]

    with pytest.raises(MissingEdgeAttributeError):
        cost.weight(7, 9, edge)


@pytest.mark.parametrize("length", [0.0, -5.0, None])
def test_non_positive_length_is_rejected(length):
    cost = make_cost()

    with pytest.raises(ValueError, match="length"):
        cost.weight(0, 1, make_edge(length=length))


def test_missing_score_without_median_raises():
    """가중 모드인데 점수도 없고 대체할 중앙값도 없으면 0으로 넘어가지 않는다."""
    cost = make_cost(0.5, 0.0)
    edge = make_edge()
    edge[SAFETY_ATTR] = None

    with pytest.raises(MissingEdgeAttributeError, match=SAFETY_ATTR):
        cost.weight(0, 1, edge)


# ── 불변성 ──────────────────────────────────────────────────────────────────


def test_weight_does_not_mutate_edge_data():
    cost = make_cost(0.5, 0.3)
    edge = make_edge(safety=0.2, accident=0.8, slope=0.4, tags=["bridge"])
    before = dict(edge)

    cost.weight(0, 1, edge)

    assert edge == before


# ── 커버리지 게이트 ─────────────────────────────────────────────────────────


def _scored_graph(n_edges: int, n_missing: int) -> nx.Graph:
    """앞쪽 n_missing개 엣지만 safety_score가 None인 그래프."""
    edges = []
    for i in range(n_edges):
        data = make_edge(length=10.0 + i, safety=0.5 + i / (2 * n_edges))
        if i < n_missing:
            data[SAFETY_ATTR] = None
        edges.append((i, i + 1, data))
    return make_graph(edges)


def test_check_coverage_reports_ratio_and_median():
    report = WeightedEdgeCost.check_coverage(_scored_graph(10, 2), min_ratio=0.5)

    assert isinstance(report, CoverageReport)
    assert report.ratios[SAFETY_ATTR] == pytest.approx(0.8)
    assert report.ratios[SLOPE_ATTR] == pytest.approx(1.0)
    assert report.ok is True
    assert SAFETY_ATTR in report.medians


def test_coverage_gate_disables_weighted_mode_and_warns_once(caplog):
    """점수가 전혀 없는 그래프(현재 운영 artifact 상태)에서는 거리 전용으로 내려간다."""
    G = make_graph([(0, 1, {"length": 100.0}), (1, 2, {"length": 50.0})])

    with caplog.at_level(logging.WARNING):
        cost = WeightedEdgeCost.from_graph(
            G, 0.5, 0.5,
            accident_ratio=LAMBDA, weight_limit=K, coverage_min_ratio=0.9,
        )

    assert cost.enabled is False
    assert cost.weight(0, 1, G[0][1]) == 100.0  # 페널티 없이 거리 그대로
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "커버리지 미달" in warnings[0].message


def test_coverage_gate_reports_which_attrs_failed():
    G = _scored_graph(10, 5)  # safety_score 적재율 0.5

    report = WeightedEdgeCost.check_coverage(G, min_ratio=0.9)

    assert report.ok is False
    assert report.missing_attrs() == [SAFETY_ATTR]


def test_median_substitution_is_counted_when_coverage_passes():
    G = _scored_graph(10, 1)  # 적재율 0.9

    cost = WeightedEdgeCost.from_graph(
        G, 0.5, 0.0,
        accident_ratio=LAMBDA, weight_limit=K, coverage_min_ratio=0.9,
    )
    assert cost.enabled is True

    cost.weight(0, 1, G[0][1])   # safety_score가 None인 엣지
    assert cost.median_substitutions == 1

    cost.weight(5, 6, G[5][6])   # 값이 있는 엣지
    assert cost.median_substitutions == 1


def test_empty_graph_is_not_weighted():
    report = WeightedEdgeCost.check_coverage(nx.Graph(), min_ratio=0.9)

    assert report.ok is False


# ── 선호도 → 계수 변환 ──────────────────────────────────────────────────────


def test_zero_preferences_give_zero_coefficients():
    assert normalize_preference_weights(0.0, 0.0, weight_limit=K) == (0.0, 0.0)


def test_preferences_within_limit_pass_through():
    assert normalize_preference_weights(0.3, 0.2, weight_limit=1.0) == (0.3, 0.2)


def test_preferences_over_limit_are_scaled_proportionally():
    """Weights의 기본값(safety=0.5, slope=0.5)처럼 합이 상한을 넘으면 비율을 지켜 축소한다."""
    alpha, beta = normalize_preference_weights(0.8, 0.4, weight_limit=0.6)

    assert alpha + beta == pytest.approx(0.6)
    assert alpha / beta == pytest.approx(2.0)  # 원래 비율 보존


def test_normalized_coefficients_are_accepted_by_the_calculator():
    alpha, beta = normalize_preference_weights(1.0, 1.0, weight_limit=0.5)

    make_cost(alpha, beta, weight_limit=0.5)  # 예외가 나지 않아야 한다


@pytest.mark.parametrize("lower,higher", [(0.1, 0.2), (0.4, 0.9)])
def test_alpha_is_monotone_in_safety_preference(lower, higher):
    a_low, _ = normalize_preference_weights(lower, 0.5, weight_limit=0.5)
    a_high, _ = normalize_preference_weights(higher, 0.5, weight_limit=0.5)

    assert a_high > a_low


@pytest.mark.parametrize("safety,slope", [(-0.1, 0.5), (0.5, 1.1)])
def test_preferences_out_of_range_are_rejected(safety, slope):
    with pytest.raises(ValueError):
        normalize_preference_weights(safety, slope, weight_limit=K)


# ── 통합: 합성 그래프에서의 A* ──────────────────────────────────────────────

# 좌표를 주고 length를 좌표 간 유클리드 거리로 맞춘 그래프.
# 그러면 유클리드 직선거리가 length에 대한 admissible heuristic이 되고,
# weighted_cost >= length이므로 가중 탐색에서도 그대로 admissible하다
# (운영의 ALT Planar 거리표를 재사용할 수 있는 근거와 같은 구조).
_POS = {"S": (0.0, 0.0), "A": (1.0, 0.0), "B": (2.0, 0.0),
        "C": (1.0, 1.0), "D": (2.0, 1.0), "T": (3.0, 0.0)}

_DIRECT = ["S", "A", "B", "T"]   # 짧지만 위험한 길
_DETOUR = ["S", "C", "D", "T"]   # 길지만 안전한 길


def _euclid(u: str, v: str) -> float:
    (x1, y1), (x2, y2) = _POS[u], _POS[v]
    return math.hypot(x2 - x1, y2 - y1)


def _two_route_graph() -> nx.Graph:
    G = nx.Graph()
    for path, (safety, accident) in ((_DIRECT, (0.0, 1.0)), (_DETOUR, (1.0, 0.0))):
        for u, v in zip(path, path[1:]):
            G.add_edge(u, v, **make_edge(
                length=_euclid(u, v), safety=safety, accident=accident, slope=1.0,
            ))
    return G


def test_astar_with_length_heuristic_matches_dijkstra_cost():
    """거리 기반 휴리스틱 A*와 Dijkstra가 같은 최소 가중 비용을 찾는다."""
    G = _two_route_graph()
    cost = make_cost(0.5, 0.0)

    astar = nx.astar_path_length(G, "S", "T", heuristic=_euclid, weight=cost.weight)
    dijkstra = nx.dijkstra_path_length(G, "S", "T", weight=cost.weight)

    assert astar == pytest.approx(dijkstra)


def test_distance_only_search_prefers_the_short_unsafe_route():
    G = _two_route_graph()
    cost = make_cost(0.0, 0.0)

    assert nx.astar_path(G, "S", "T", heuristic=_euclid, weight=cost.weight) == _DIRECT


def test_raising_safety_weight_switches_to_the_safe_detour():
    """안전 가중치를 올리면 더 먼 길이라도 안전한 우회로를 고른다."""
    G = _two_route_graph()
    cost = make_cost(0.5, 0.0)

    assert nx.astar_path(G, "S", "T", heuristic=_euclid, weight=cost.weight) == _DETOUR


def test_raising_comfort_weight_switches_to_the_flat_detour():
    """편안 가중치를 올리면 경사가 심한 최단 구간 대신 평탄한 우회로를 고른다."""
    G = nx.Graph()
    for path, slope in ((_DIRECT, 0.0), (_DETOUR, 1.0)):
        for u, v in zip(path, path[1:]):
            G.add_edge(u, v, **make_edge(length=_euclid(u, v), slope=slope))

    flat_only = make_cost(0.0, 0.0)
    comfort = make_cost(0.0, 0.5)

    assert nx.astar_path(G, "S", "T", heuristic=_euclid, weight=flat_only.weight) == _DIRECT
    assert nx.astar_path(G, "S", "T", heuristic=_euclid, weight=comfort.weight) == _DETOUR


def test_total_distance_is_independent_of_search_cost():
    """탐색 비용이 바뀌어도 실제 이동 거리는 length 합 그대로여야 한다."""
    G = _two_route_graph()
    path = nx.astar_path(G, "S", "T", heuristic=_euclid,
                         weight=make_cost(0.5, 0.0).weight)

    total_m = sum(G[u][v]["length"] for u, v in zip(path, path[1:]))

    assert total_m == pytest.approx(sum(_euclid(u, v) for u, v in zip(_DETOUR, _DETOUR[1:])))


@pytest.mark.parametrize(
    "accidents, expected_missing",
    [([0.0, None, 1.0], 0.5), ([0.0, None, 0.4], 0.2), ([None, None], 0.0)],
)
def test_feature_cache_initializes_accident_median(accidents, expected_missing):
    """기동 캐시가 사고 점수의 0과 결측을 구분하고 결측만 중앙값으로 채운다."""
    graph = nx.Graph()
    for i, accident in enumerate(accidents):
        graph.add_edge(i, i + 1, **make_edge(safety=0.8, accident=accident))

    precompute_scoring_features(graph)

    for i, accident in enumerate(accidents):
        expected = expected_missing if accident is None else accident
        features = path_feature_averages(graph, [i, i + 1])
        assert features["safety"] == pytest.approx(1 - (0.5 * 0.2 + 0.5 * expected))
        assert graph[i][i + 1][ACCIDENT_ATTR] == accident


def test_feature_cache_initializes_without_edges():
    precompute_scoring_features(nx.Graph())
