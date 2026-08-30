"""작은 거리표로 ALNS 연산자와 상태 전이를 검증한다."""

from copy import deepcopy
from dataclasses import replace
from itertools import permutations
from math import inf, log
from random import Random
from unittest.mock import Mock

import pytest

import src.route_engine.waypoint_alns as module
from src.route_engine.waypoint_alns import (
    ALNSConfig,
    _accept,
    _AdaptivePool,
    _destroy,
    _Evaluator,
    _repair,
    alns_search,
)
from src.route_engine.waypoint_beam import beam_search
from src.route_engine.waypoint_types import WaypointOrder


def candidates(*ids):
    return [dict(node_id=i, lat=37.5, lon=127.0) for i in ids]


def distance(a, b):
    return abs(a - b) * 100.0


def run(**overrides):
    args = dict(
        candidates=candidates(1, 2, 3, 4),
        cost=distance,
        initial_ids=(1, 2),
        start_id=0,
        end_id=0,
        target_m=750.0,
        config=ALNSConfig(iterations=30, seed=7),
    )
    args.update(overrides)
    return alns_search(**args)


def test_zero_iterations_recomputes_initial_distance():
    result = run(config=ALNSConfig(iterations=0))
    assert result.best == WaypointOrder((1, 2), 400.0, 350.0)
    assert result.current == result.best
    assert result.iterations == 0
    assert result.cost_calls == 3


@pytest.mark.parametrize("end_id", [0, 5])
@pytest.mark.parametrize("seed", range(8))
def test_preserves_count_membership_endpoints_and_best(end_id, seed):
    result = run(end_id=end_id, config=ALNSConfig(iterations=20, seed=seed))
    baseline = _Evaluator(distance, 0, end_id, 750, None).evaluate((1, 2))
    assert result.best.error_m <= baseline.error_m
    for order in (result.best, result.current):
        assert len(order.waypoint_ids) == len(set(order.waypoint_ids)) == 2
        assert set(order.waypoint_ids) <= {1, 2, 3, 4}
        stops = (0, *order.waypoint_ids, end_id)
        expected = sum(distance(a, b) for a, b in zip(stops, stops[1:]))
        assert order.distance_m == expected
        assert order.error_m == abs(expected - 750)
    assert sum(s.uses for s in result.destroy_stats) == result.iterations
    assert sum(s.uses for s in result.repair_stats) == result.iterations


def test_single_waypoint_matches_exhaustive_optimum():
    result = run(initial_ids=(1,), target_m=780)
    expected = min(abs(distance(0, i) + distance(i, 0) - 780) for i in (1, 2, 3, 4))
    assert result.best.error_m == expected
    assert result.best.waypoint_ids == (4,)


def test_exact_target_returns_without_destroy():
    result = run(target_m=400)
    assert result.stop_reason == "exact_target"
    assert result.iterations == result.accepted_moves == 0


def test_beam_output_can_be_passed_without_alns_calling_beam():
    pool = candidates(1, 2, 3, 4)
    initial = beam_search(
        candidates=pool,
        cost=distance,
        start_id=0,
        end_id=0,
        target_m=750,
        waypoint_count=2,
        beam_width=2,
    ).orders[0]
    result = run(initial_ids=initial.waypoint_ids)
    assert result.best.error_m <= initial.error_m


def test_seed_is_deterministic_and_does_not_mutate_inputs_or_global_rng():
    import random

    pool, ids = candidates(4, 3, 2, 1), [1, 2]
    before = deepcopy((pool, ids))
    state = random.getstate()
    first = run(candidates=pool, initial_ids=ids)
    second = run(candidates=list(reversed(pool)), initial_ids=ids)
    assert first == second
    assert (pool, ids) == before
    assert random.getstate() == state


@pytest.mark.parametrize("circular", [False, True])
@pytest.mark.parametrize("method", ["random", "sequence"])
@pytest.mark.parametrize("count", [1, 2, 4])
def test_destroy_removes_exactly_count_preserving_remaining_order(
    method, count, circular
):
    ids = (1, 2, 3, 4)
    result = _destroy(ids, count, method, Random(4), circular)
    assert len(result) == 4 - count
    assert result == tuple(i for i in ids if i in result)


def test_sequence_wraps_only_for_circular_routes():
    rng = Mock()
    rng.randrange.return_value = 3
    assert _destroy((1, 2, 3, 4), 2, "sequence", rng, True) == (2, 3)
    rng.randrange.assert_called_once_with(4)
    rng.reset_mock()
    rng.randrange.return_value = 2
    assert _destroy((1, 2, 3, 4), 2, "sequence", rng, False) == (1, 2)
    rng.randrange.assert_called_once_with(3)


def test_greedy_repair_chooses_target_error_not_shortest_insertion():
    evaluator = _Evaluator(distance, 0, 0, 790, None)
    result = _repair((1,), (1, 2, 3, 4), 2, "greedy", evaluator, Random(0), None)
    assert result.waypoint_ids == (1, 4)
    assert result.distance_m == 800


def test_repair_can_reinsert_removed_node_or_choose_unselected_node():
    evaluator = _Evaluator(distance, 0, 0, 400, None)
    assert _repair(
        (1,), (1, 2), 2, "greedy", evaluator, Random(0), None
    ).waypoint_ids == (1, 2)
    evaluator = _Evaluator(distance, 0, 0, 800, None)
    assert (
        4
        in _repair(
            (1,), (1, 2, 3, 4), 2, "greedy", evaluator, Random(0), None
        ).waypoint_ids
    )


def test_random_order_repair_selects_random_node_but_best_position():
    rng = Mock()
    rng.shuffle.side_effect = lambda values: values.reverse()
    evaluator = _Evaluator(distance, 0, 0, 790, None)
    result = _repair((1,), (1, 2, 3, 4), 2, "random_order", evaluator, rng, None)
    assert result.waypoint_ids == (1, 4)
    assert evaluator.evaluated_orders == 2


def test_candidate_limit_happens_before_cost_calls():
    callback = Mock(side_effect=distance)
    evaluator = _Evaluator(callback, 0, 0, 100, None)
    _repair((), tuple(range(1, 1001)), 1, "greedy", evaluator, Random(0), 3)
    assert evaluator.evaluated_orders == 3
    assert callback.call_count == 6


def test_unreachable_insertions_are_skipped():
    def unreachable(a, b):
        return inf if 3 in (a, b) else distance(a, b)

    result = run(cost=unreachable)
    assert 3 not in result.best.waypoint_ids


def test_failed_repair_retains_current_and_best(monkeypatch):
    monkeypatch.setattr(module, "_repair", lambda *args: None)
    result = run(config=ALNSConfig(iterations=3))
    assert result.best == result.current == WaypointOrder((1, 2), 400, 350)
    assert result.failed_repairs == 3
    assert result.accepted_moves == 0


def test_best_is_preserved_after_accepting_worse_candidate(monkeypatch):
    moves = iter((WaypointOrder((1, 3), 600, 150), WaypointOrder((1, 2), 400, 350)))
    monkeypatch.setattr(module, "_repair", lambda *args: next(moves))
    monkeypatch.setattr(module, "_accept", lambda *args: True)
    result = run(config=ALNSConfig(iterations=2))
    assert result.best.waypoint_ids == (1, 3)
    assert result.current.waypoint_ids == (1, 2)
    assert result.accepted_moves == 2


def test_simulated_annealing_probability_and_zero_temperature():
    rng = Mock()
    temperature = 100 / log(2)
    rng.random.return_value = 0.49
    assert _accept(100, temperature, rng)
    rng.random.return_value = 0.51
    assert not _accept(100, temperature, rng)
    assert not _accept(1, 0, rng)
    assert _accept(0, 0, rng) and _accept(-1, 0, rng)
    assert not _accept(1e300, 1e-300, rng)


def test_segment_update_uses_average_reward_and_skips_unused():
    pool = _AdaptivePool(("a", "b"))
    pool.segment_uses[0], pool.scores[0] = 2, 6
    pool.update(0.25)
    assert pool.weights == [1.5, 1]
    assert pool.segment_uses == [0, 0] and pool.scores == [0, 0]
    pool.segment_uses[0] = 1
    pool.update(1)
    assert pool.weights[0] == 1e-6


def test_repeated_same_solution_is_not_rewarded(monkeypatch):
    monkeypatch.setattr(
        module, "_repair", lambda *args: WaypointOrder((1, 2), 400, 350)
    )
    result = run(config=ALNSConfig(iterations=4, segment_length=1, reaction_factor=0.5))
    assert result.accepted_moves == 0
    assert all(s.weight <= 1 for s in result.destroy_stats + result.repair_stats)
    assert any(s.weight < 1 for s in result.destroy_stats)


@pytest.mark.parametrize("budget", [3, 4, 7, 30])
def test_cost_budget_is_hard_limit_and_returns_valid_best(budget):
    callback = Mock(side_effect=distance)
    result = run(cost=callback, config=ALNSConfig(max_cost_calls=budget))
    assert result.cost_calls == callback.call_count == budget
    assert result.stop_reason == "cost_budget"
    assert result.best.error_m <= 350


@pytest.mark.parametrize("value", [-1, float("nan"), -inf])
def test_invalid_cost_is_not_silently_accepted(value):
    with pytest.raises(ValueError):
        run(cost=lambda a, b: value)


def test_cost_exception_propagates():
    with pytest.raises(RuntimeError, match="provider"):
        run(cost=Mock(side_effect=RuntimeError("provider")))


def test_initial_unreachable_or_overflow_raises():
    with pytest.raises(ValueError, match="도달"):
        run(cost=lambda a, b: inf)
    with pytest.raises(ValueError, match="유한"):
        run(cost=lambda a, b: 1e308)


@pytest.mark.parametrize("ids", [(), (1, 1), (0, 1), (9,), (True,), (1.0,)])
def test_invalid_initial_ids(ids):
    with pytest.raises(ValueError):
        run(initial_ids=ids)


@pytest.mark.parametrize(
    "pool", [candidates(1, 1), [dict(node_id=1)], candidates(True)]
)
def test_invalid_candidates(pool):
    with pytest.raises(ValueError):
        run(candidates=pool)


@pytest.mark.parametrize(
    "name,value",
    [
        ("iterations", -1),
        ("iterations", True),
        ("segment_length", 0),
        ("removal_fraction", 0),
        ("removal_fraction", 1.1),
        ("removal_fraction", float("nan")),
        ("cooling_rate", 0),
        ("cooling_rate", inf),
        ("reaction_factor", -0.1),
        ("start_temperature_m", -1),
        ("start_temperature_m", inf),
        ("candidate_limit", 0),
        ("max_cost_calls", 2),
        ("seed", True),
    ],
)
def test_invalid_configuration(name, value):
    with pytest.raises(ValueError):
        run(config=replace(ALNSConfig(), **{name: value}))


def test_full_removal_requires_enough_sampled_candidates():
    with pytest.raises(ValueError):
        run(config=ALNSConfig(removal_fraction=1, candidate_limit=1))


def test_small_complete_graph_matches_oracle_for_fixed_fixture():
    result = run(config=ALNSConfig(iterations=100, removal_fraction=1, seed=3))
    oracle = min(
        abs(sum(distance(a, b) for a, b in zip((0, *ids), (*ids, 0))) - 750)
        for ids in permutations((1, 2, 3, 4), 2)
    )
    assert result.best.error_m == oracle
