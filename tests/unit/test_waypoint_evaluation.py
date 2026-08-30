"""실제 도로 재통행과 Beam·ALNS의 공통 평가 규칙을 검증한다."""

from dataclasses import replace
from itertools import permutations
from math import inf
from unittest.mock import Mock

import networkx as nx
import pytest

import src.route_engine.waypoint_alns as alns_module
from src.route_engine.waypoint_alns import ALNSConfig, _accept, alns_search
from src.route_engine.waypoint_beam import beam_search
from src.route_engine.waypoint_evaluation import (
    RouteEvaluator,
    WaypointObjective,
    attach_route_metrics,
)
from src.route_engine.waypoint_types import RouteMetrics, WaypointOrder


def providers(graph, cache_size=16):
    """작은 그래프의 고정 최단거리와 실제 도로 평가 공급자를 만든다."""

    def path(a, b):
        """도달 불가일 때 None을 반환하는 최단 노드열 공급자다."""
        try:
            return nx.shortest_path(graph, a, b, weight="length")
        except nx.NetworkXNoPath:
            return None

    def cost(a, b):
        """같은 그래프의 최단거리만 반환한다."""
        try:
            return nx.shortest_path_length(graph, a, b, weight="length")
        except nx.NetworkXNoPath:
            return inf

    return cost, RouteEvaluator(
        path, lambda a, b: graph[a][b]["length"], cache_size=cache_size
    )


@pytest.fixture
def fixture():
    """450m 순환과 400m 막다른 길 왕복이 경쟁하는 그래프를 만든다."""
    graph = nx.Graph()
    graph.add_weighted_edges_from(
        [(0, 1, 150), (1, 2, 150), (2, 0, 150), (0, 4, 100), (4, 5, 100)],
        weight="length",
    )
    cost, route = providers(graph)
    pool = [dict(node_id=n, lat=0.0, lon=0.0) for n in (1, 2, 4, 5)]
    return dict(candidates=pool, cost=cost, start_id=0, end_id=0, target_m=400), route


def order(distance, repeated, target=400):
    """비교 규칙 검증용 평가 완료 조합을 만든다."""
    return WaypointOrder(
        (1,), distance, abs(distance - target), RouteMetrics(distance, repeated)
    )


def test_round_trip_counts_only_second_traversal(fixture):
    """왕복 400m 중 돌아오는 200m만 재통행으로 계산한다."""
    _, route = fixture
    assert route((0, 5, 0)) == RouteMetrics(400, 200)
    assert route((0, 5, 0)).overlap_ratio == 0.5


def test_closed_cycle_has_no_overlap_and_endpoints_are_not_penalized(fixture):
    """출발지 복귀 자체는 도로 재통행이 아니다."""
    _, route = fixture
    assert route((0, 1, 2, 0)) == RouteMetrics(450, 0)


def test_length_weighting_and_three_traversals():
    """횟수 비율이 아니라 길이를 사용하고 세 번째 통행도 누적한다."""
    graph = nx.Graph()
    graph.add_weighted_edges_from([(0, 1, 10), (1, 2, 90)], weight="length")
    _, route = providers(graph)
    assert route((0, 1, 0, 1, 2)) == RouteMetrics(120, 20)


def test_zero_distance_and_unreachable_route():
    """이동 없는 경로와 단절된 경로를 구별한다."""
    graph = nx.empty_graph(2)
    _, route = providers(graph)
    assert route((0, 0)) == RouteMetrics(0, 0)
    assert route((0, 0)).overlap_ratio == 0
    assert route.cache_info().misses == 0
    assert route((0, 1)) is None


def test_reverse_calls_share_bounded_cache(fixture):
    """역방향은 같은 구간을 사용하고 캐시를 명시적으로 초기화할 수 있다."""
    _, route = fixture
    route((0, 5, 0))
    assert route.cache_info().misses == 1
    assert route.cache_info().hits == 1
    route.cache_clear()
    assert route.cache_info().currsize == route.cache_info().misses == 0
    path = Mock(side_effect=lambda a, b: (a, b))
    small = RouteEvaluator(path, lambda a, b: 1, cache_size=1)
    small((0, 1, 2, 0))
    assert small.cache_info().currsize == 1


@pytest.mark.parametrize("size", [-1, True, 1.5])
def test_invalid_cache_size(size):
    """캐시 크기 설정 오류를 거부한다."""
    with pytest.raises(ValueError):
        RouteEvaluator(lambda a, b: (a, b), lambda a, b: 1, cache_size=size)


@pytest.mark.parametrize("nodes", [(), (0,), (1, 0), (0, True), (0, 1.0)])
def test_invalid_path_provider_result(nodes):
    """출발·도착 또는 노드 ID가 잘못된 복원 결과를 거부한다."""
    route = RouteEvaluator(lambda a, b: nodes, lambda a, b: 1)
    with pytest.raises(ValueError):
        route((0, 1))


@pytest.mark.parametrize("length", [-1, inf, float("nan")])
def test_invalid_edge_length(length):
    """복원 경로에 잘못된 엣지 길이가 있으면 실패한다."""
    route = RouteEvaluator(lambda a, b: (a, b), lambda a, b: length)
    with pytest.raises(ValueError):
        route((0, 1))


@pytest.mark.parametrize("values", [(1, 2), (-1, 0), (inf, 1), (1, float("nan"))])
def test_invalid_metrics(values):
    """불가능한 거리 관계와 비유한 값을 거부한다."""
    with pytest.raises(ValueError):
        RouteMetrics(*values)


def test_graph_or_weight_mismatch_is_not_hidden():
    """cost와 경로 공급자가 다른 거리 기준을 쓰면 즉시 알린다."""
    with pytest.raises(ValueError, match="거리가 다릅니다"):
        attach_route_metrics(
            WaypointOrder((1,), 100, 0), lambda stops: RouteMetrics(110, 0), 0, 0
        )


def test_within_tolerance_has_priority_over_short_nonoverlapping_route():
    """짧고 겹침 없는 경로보다 목표 범위를 만족하는 경로가 우선이다."""
    objective = WaypointObjective(400, 0.125)
    assert objective.rank(order(400, 200)) < objective.rank(order(50, 0))
    assert objective.rank(order(450, 0)) < objective.rank(order(400, 200))


def test_outside_tolerance_prefers_distance_then_overlap():
    """범위 밖에서는 거리 오차, 동점이면 재통행을 비교한다."""
    objective = WaypointObjective(400, 0.05)
    assert objective.rank(order(450, 200)) < objective.rank(order(500, 0))
    assert objective.rank(order(450, 0)) < objective.rank(order(450, 200))


def test_inside_ties_prefer_distance_then_ids():
    """범위 안 재통행 비율 동점은 거리 오차와 ID로 결정한다."""
    objective = WaypointObjective(400, 0.125)
    assert objective.rank(order(400, 0)) < objective.rank(order(450, 0))
    a = order(400, 0)
    assert objective.rank(a) < objective.rank(replace(a, waypoint_ids=(2,)))


def test_tolerance_boundary_is_inclusive():
    """상·하한을 포함하되 초과한 경로는 범위 밖이다."""
    objective = WaypointObjective(400, 0.125)
    assert objective.within_tolerance(order(350, 0))
    assert objective.within_tolerance(order(450, 0))
    assert not objective.within_tolerance(order(450.001, 0))
    assert WaypointObjective(400, 0).within_tolerance(order(400, 200))


@pytest.mark.parametrize("value", [-0.1, 1, True, inf, float("nan")])
def test_invalid_tolerance(value):
    """허용 비율의 범위와 타입을 검사한다."""
    with pytest.raises(ValueError):
        WaypointObjective(400, value)


def test_beam_overlap_mode_matches_exhaustive_small_fixture(fixture):
    """충분한 Beam 폭에서는 실제 그래프 전수 비교 결과와 일치한다."""
    args, route = fixture
    baseline = beam_search(**args, waypoint_count=2, beam_width=20).orders[0]
    result = beam_search(
        **args,
        waypoint_count=2,
        beam_width=20,
        tolerance_ratio=0.125,
        evaluate_route=route,
    )
    objective = WaypointObjective(400, 0.125)
    exhaustive = []
    for ids in permutations((1, 2, 4, 5), 2):
        metrics = route((0, *ids, 0))
        exhaustive.append(
            WaypointOrder(
                ids, metrics.distance_m, abs(metrics.distance_m - 400), metrics
            )
        )
    assert result.orders[0] == min(exhaustive, key=objective.rank)
    assert baseline.error_m == 0
    assert result.orders[0].distance_m == 450
    assert result.orders[0].route_metrics.overlap_ratio == 0
    assert result.route_evaluations > len(result.orders)


def test_beam_uses_overlap_during_pruning_not_only_final_sort():
    """폭 1인 중간 단계에서도 경로 평가가 다음 생존자를 바꾼다."""
    args = dict(
        candidates=[dict(node_id=n, lat=0, lon=0) for n in (1, 2, 3)],
        cost=lambda a, b: 100,
        start_id=0,
        end_id=9,
        target_m=300,
        waypoint_count=2,
        beam_width=1,
    )
    seen = []

    def evaluate(stops):
        """중간 단계 순서별로 다른 재통행을 주는 독립 테스트 공급자다."""
        seen.append(stops)
        length = (len(stops) - 1) * 100
        return RouteMetrics(length, 0 if stops[1] == 2 else length / 2)

    baseline = beam_search(**args)
    revised = beam_search(**args, tolerance_ratio=0.4, evaluate_route=evaluate)
    assert baseline.orders[0].waypoint_ids[0] == 1
    assert revised.orders[0].waypoint_ids[0] == 2
    assert any(len(stops) == 3 for stops in seen)


def test_alns_continues_from_exact_distance_and_reduces_overlap(fixture):
    """거리 오차 0인 왕복 해도 종료하지 않고 덜 겹치는 순환으로 개선한다."""
    args, route = fixture
    result = alns_search(
        **args,
        initial_ids=(4, 5),
        tolerance_ratio=0.125,
        evaluate_route=route,
        config=ALNSConfig(
            iterations=30, removal_fraction=1, seed=0, start_temperature_score=0
        ),
    )
    assert result.iterations > 0
    assert result.best.distance_m == 450
    assert result.best.route_metrics.overlap_ratio == 0
    assert result.stop_reason == "iterations"
    assert result.route_evaluations == result.evaluated_orders


def test_alns_zero_distance_error_and_zero_overlap_can_stop(fixture):
    """두 목표를 모두 0으로 달성하면 즉시 종료한다."""
    args, route = fixture
    result = alns_search(
        **{**args, "target_m": 450},
        initial_ids=(1, 2),
        evaluate_route=route,
        tolerance_ratio=0.05,
        config=ALNSConfig(start_temperature_score=0.05),
    )
    assert result.stop_reason == "exact_target_no_overlap"
    assert result.iterations == 0


def test_alns_reward_and_best_use_overlap_score(monkeypatch, fixture):
    """거리 오차가 늘어도 범위 안 재통행 개선이면 최적 해와 보상을 갱신한다."""
    args, route = fixture
    better = attach_route_metrics(WaypointOrder((1, 2), 450, 50), route, 0, 0)
    worse = attach_route_metrics(WaypointOrder((4, 5), 400, 0), route, 0, 0)
    moves = iter([better, worse])
    monkeypatch.setattr(alns_module, "_repair", lambda *args: next(moves))
    monkeypatch.setattr(alns_module, "_accept", lambda *args: True)
    result = alns_search(
        **args,
        initial_ids=(4, 5),
        evaluate_route=route,
        tolerance_ratio=0.125,
        config=ALNSConfig(
            iterations=2, segment_length=1, reaction_factor=1, start_temperature_score=1
        ),
    )
    assert result.best == better and result.current == worse
    assert any(s.weight == 6 for s in result.destroy_stats)


def test_score_temperature_controls_acceptance_probability():
    """무차원 점수 증가 0.1, 온도 0.1이면 수락 확률은 exp(-1)이다."""
    rng = Mock()
    rng.random.return_value = 0.36
    assert _accept(0.1, 0.1, rng)
    rng.random.return_value = 0.38
    assert not _accept(0.1, 0.1, rng)


@pytest.mark.parametrize("end", [0, 2])
def test_overlap_alns_reproducible_and_budget_limited(fixture, end):
    """순환·편도 모두 동일 입력을 재현하고 cost 호출 상한을 지킨다."""
    args, route = fixture
    args = {**args, "end_id": end}
    config = ALNSConfig(max_cost_calls=40, start_temperature_score=0.1)
    first = alns_search(
        **args,
        initial_ids=(4, 5),
        evaluate_route=route,
        tolerance_ratio=0.05,
        config=config,
    )
    route.cache_clear()
    second = alns_search(
        **args,
        initial_ids=(4, 5),
        evaluate_route=route,
        tolerance_ratio=0.05,
        config=config,
    )
    assert first == second
    assert first.cost_calls <= 40
    assert first.best.route_metrics is not None


def test_missing_provider_or_temperature_is_rejected(fixture):
    """평가 모드나 온도를 일부만 지정한 실행을 거부한다."""
    args, route = fixture
    with pytest.raises(ValueError):
        beam_search(**args, waypoint_count=2, beam_width=2, tolerance_ratio=0.05)
    with pytest.raises(ValueError):
        beam_search(**args, waypoint_count=2, beam_width=2, evaluate_route=route)
    with pytest.raises(ValueError):
        alns_search(
            **args, initial_ids=(4, 5), tolerance_ratio=0.05, evaluate_route=route
        )
    with pytest.raises(ValueError):
        alns_search(
            **args, initial_ids=(4, 5), config=ALNSConfig(start_temperature_score=1)
        )


def test_provider_exception_is_not_hidden(fixture):
    """경로 공급자의 구현 오류를 도달 불가로 숨기지 않는다."""
    args, _ = fixture
    with pytest.raises(RuntimeError, match="provider"):
        beam_search(
            **args,
            waypoint_count=2,
            beam_width=2,
            tolerance_ratio=0.05,
            evaluate_route=Mock(side_effect=RuntimeError("provider")),
        )


@pytest.mark.parametrize("temperature", [-1, True, inf, float("nan")])
def test_invalid_score_temperature_is_rejected(fixture, temperature):
    """재통행 모드의 온도 오류를 계산 전에 거부한다."""
    args, route = fixture
    with pytest.raises(ValueError, match="start_temperature_score"):
        alns_search(
            **args,
            initial_ids=(4, 5),
            tolerance_ratio=0.05,
            evaluate_route=route,
            config=ALNSConfig(start_temperature_score=temperature),
        )


def test_path_unavailable_skips_beam_and_rejects_alns_initial(fixture):
    """도로 복원을 못 한 순서는 재통행 0인 해로 사용하지 않는다."""
    args, _ = fixture

    def route(stops):
        """모든 구간 복원이 불가능한 공급자를 흉내 낸다."""
        return None

    beam = beam_search(
        **args,
        waypoint_count=2,
        beam_width=2,
        tolerance_ratio=0.05,
        evaluate_route=route,
    )
    assert not beam.orders
    with pytest.raises(ValueError, match="도달"):
        alns_search(
            **args,
            initial_ids=(4, 5),
            tolerance_ratio=0.05,
            evaluate_route=route,
            config=ALNSConfig(start_temperature_score=0),
        )
