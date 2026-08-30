"""거리표로 탐색 규칙을 검증한다. 실제 도보 그래프 벤치마크가 아니다."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
from itertools import permutations
from math import inf
from unittest.mock import Mock

import pytest

from src.route_engine.waypoint_beam import WaypointOrder, beam_search


def candidates_for(*node_ids):
    return [{"node_id": node_id, "lat": 37.5, "lon": 126.9} for node_id in node_ids]


def line_cost(a, b):
    # 동일한 선 위에 놓인 노드들의 대칭 거리표(m).
    positions = {0: 0.0, 1: 1.0, 2: 3.0, 3: 6.0, 4: 8.0}
    assert isinstance(a, int) and not isinstance(a, bool)
    assert isinstance(b, int) and not isinstance(b, bool)
    return abs(positions[a] - positions[b])


def run_search(**overrides):
    arguments = dict(
        candidates=candidates_for(1, 2, 3),
        cost=line_cost,
        start_id=0,
        end_id=0,
        target_m=10.0,
        waypoint_count=2,
        beam_width=6,
    )
    arguments.update(overrides)
    return beam_search(**arguments)


def route_distance(ids, cost, start, end):
    stops = (start, *ids, end)
    return sum(cost(a, b) for a, b in zip(stops, stops[1:]))


@pytest.mark.parametrize("end_id", [0, 4])
@pytest.mark.parametrize("waypoint_count", [1, 2, 3])
def test_wide_beam_matches_exhaustive_search(end_id, waypoint_count):
    # 각 깊이의 순열 수는 최대 6. B=6이면 가지치기 없이 전체 순열과 비교한다.
    result = run_search(end_id=end_id, waypoint_count=waypoint_count)
    expected = []
    for ids in permutations((1, 2, 3), waypoint_count):
        distance = route_distance(ids, line_cost, 0, end_id)
        expected.append(WaypointOrder(ids, distance, abs(distance - 10.0)))
    expected.sort(key=lambda order: (order.error_m, order.waypoint_ids))
    assert result.orders == tuple(expected)


@pytest.mark.parametrize("beam_width", [1, 2, 5])
@pytest.mark.parametrize("waypoint_count", [1, 2, 3])
@pytest.mark.parametrize("end_id", [0, 4])
def test_streaming_top_b_matches_batch_reference(beam_width, waypoint_count, end_id):
    # 독립 기준 구현: 모든 확장 순서를 리스트로 모으고 매번 거리를 재합산.
    orders = [()]
    for _ in range(waypoint_count):
        expanded = [
            (*ids, node_id)
            for ids in orders
            for node_id in (1, 2, 3)
            if node_id not in ids
        ]
        expanded.sort(
            key=lambda ids: (abs(route_distance(ids, line_cost, 0, end_id) - 10.0), ids)
        )
        orders = expanded[:beam_width]

    result = run_search(
        beam_width=beam_width,
        waypoint_count=waypoint_count,
        end_id=end_id,
    )
    assert [order.waypoint_ids for order in result.orders] == orders
    assert len(result.orders) <= beam_width


def test_global_top_b_can_keep_two_children_of_the_same_parent():
    # 출발지(0)가 중심인 별 모양 그래프의 최단 거리.
    # 첫 단계 부모는 1, 2. 다음 전역 Top-2는 모두 부모 1에서 나와야 한다.
    spokes = {0: 0.0, 1: 9.0, 2: 8.0, 3: 1.0, 4: 1.2}

    def cost(a, b):
        return 0.0 if a == b else spokes[a] + spokes[b]

    result = run_search(
        candidates=candidates_for(1, 2, 3, 4),
        cost=cost,
        target_m=20.0,
        beam_width=2,
    )
    assert [order.waypoint_ids for order in result.orders] == [(1, 3), (1, 4)]
    assert result.evaluated_candidates == 10
    assert result.cost_calls == 20


def test_return_leg_is_replaced_not_accumulated():
    distances = {(0, 1): 1000.0, (0, 2): 1200.0, (1, 2): 1500.0}

    def cost(a, b):
        return distances[tuple(sorted((a, b)))]

    result = run_search(candidates=candidates_for(1, 2), cost=cost, target_m=3700.0)
    assert len(result.orders) == 2
    for order in result.orders:
        assert order.distance_m == 3700.0
        assert order.error_m == 0.0


def test_inputs_are_preserved_and_ties_are_deterministic():
    candidates = candidates_for(3, 1, 2)
    original = deepcopy(candidates)
    result = run_search(candidates=candidates)
    assert candidates == original
    assert result == run_search(candidates=list(reversed(candidates)))
    assert result.orders[0].waypoint_ids == (1, 3)


def test_coordinates_do_not_change_selection():
    candidates = candidates_for(1, 2, 3)
    for candidate in candidates:
        candidate.update(lat=0.0, lon=0.0)
    assert run_search(candidates=candidates) == run_search()


def test_endpoints_are_not_selected_and_waypoints_are_unique():
    result = run_search(candidates=candidates_for(0, 1, 2, 3, 4), end_id=4)
    assert result == run_search(end_id=4)
    for order in result.orders:
        assert len(order.waypoint_ids) == len(set(order.waypoint_ids)) == 2
        assert 0 not in order.waypoint_ids and 4 not in order.waypoint_ids


def test_same_last_node_does_not_merge_different_orders():
    result = run_search()
    ids = [order.waypoint_ids for order in result.orders]
    assert (1, 3) in ids and (2, 3) in ids


def test_unreachable_candidate_does_not_abort_other_combinations():
    def cost(a, b):
        return inf if 3 in (a, b) else line_cost(a, b)

    result = run_search(cost=cost)
    assert {order.waypoint_ids for order in result.orders} == {(1, 2), (2, 1)}
    assert result.evaluated_candidates == 7
    assert result.cost_calls == 11


def test_all_unreachable_returns_empty_result_with_counters():
    result = run_search(cost=lambda a, b: inf)
    assert result.orders == ()
    assert result.evaluated_candidates == result.cost_calls == 3


def test_unreachable_tail_is_rejected():
    # 출발지 쪽과 목적지가 분리된 무방향 그래프의 거리를 모사한다.
    def cost(a, b):
        return inf if 4 in (a, b) else line_cost(a, b)

    result = run_search(cost=cost, end_id=4)
    assert result.orders == ()
    assert result.cost_calls == 6


def test_dead_end_at_later_depth_does_not_return_partial_order():
    def cost(a, b):
        return line_cost(a, b) if {a, b} <= {0, 1} else inf

    result = run_search(cost=cost)
    assert result.orders == ()
    assert result.evaluated_candidates == 5
    assert result.cost_calls == 6


def test_zero_distances_are_valid_but_do_not_imply_target_success():
    result = run_search(cost=lambda a, b: 0.0)
    assert len(result.orders) == 6
    assert all(order.distance_m == 0.0 for order in result.orders)
    assert all(order.error_m == 10.0 for order in result.orders)


def test_overshoot_is_returned_instead_of_silently_pruned():
    result = run_search(target_m=1.0)
    assert result.orders
    assert result.orders[0].distance_m > 1.0


def test_calls_are_measured_without_pairwise_precomputation():
    callback = Mock(side_effect=line_cost)
    result = run_search(cost=callback, waypoint_count=1)
    assert result.evaluated_candidates == 3
    assert result.cost_calls == callback.call_count == 6
    assert all(
        call.args[0] == 0 or call.args[1] == 0 for call in callback.call_args_list
    )


@pytest.mark.parametrize("name", ["waypoint_count", "beam_width"])
@pytest.mark.parametrize("value", [0, -1, 1.5, True])
def test_invalid_positive_integer_parameters(name, value):
    with pytest.raises(ValueError, match=name):
        run_search(**{name: value})


@pytest.mark.parametrize("value", [0.0, -1.0, inf, -inf, float("nan")])
def test_invalid_target(value):
    with pytest.raises(ValueError, match="target_m"):
        run_search(target_m=value)


@pytest.mark.parametrize("name", ["start_id", "end_id"])
@pytest.mark.parametrize("value", [1.5, True, "1"])
def test_invalid_endpoint_ids(name, value):
    with pytest.raises(ValueError, match="ID"):
        run_search(**{name: value})


@pytest.mark.parametrize("value", [1.5, True, "1"])
def test_invalid_candidate_ids(value):
    with pytest.raises(ValueError, match="node_id"):
        run_search(candidates=candidates_for(value))


@pytest.mark.parametrize("missing", ["node_id", "lat", "lon"])
def test_required_candidate_fields(missing):
    candidates = candidates_for(1, 2, 3)
    del candidates[0][missing]
    with pytest.raises(ValueError, match="node_id, lat, lon"):
        run_search(candidates=candidates)


def test_duplicate_ids_are_rejected():
    with pytest.raises(ValueError, match="중복"):
        run_search(candidates=candidates_for(1, 2, 1))


@pytest.mark.parametrize("ids", [(), (1,), (0, 1, 4)])
def test_insufficient_eligible_candidates(ids):
    with pytest.raises(ValueError, match="후보 수"):
        run_search(candidates=candidates_for(*ids), end_id=4)


@pytest.mark.parametrize("value", [-1.0, -inf, float("nan")])
def test_invalid_cost_values_are_rejected(value):
    with pytest.raises(ValueError, match="cost"):
        run_search(cost=lambda a, b: value)


def test_cost_provider_errors_are_not_hidden():
    callback = Mock(side_effect=RuntimeError("provider failed"))
    with pytest.raises(RuntimeError, match="provider failed"):
        run_search(cost=callback)


def test_total_distance_overflow_is_rejected():
    with pytest.raises(ValueError, match="누적 거리"):
        run_search(cost=lambda a, b: 1e308)


def test_returned_order_is_immutable():
    best = run_search().orders[0]
    with pytest.raises(FrozenInstanceError):
        best.distance_m = 0.0
