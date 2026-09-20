"""편도 밀도 층화 runner의 조건 교차·시드·가중치 계약."""

import networkx as nx
import pytest

from benchmarks import aggregate_results
from benchmarks import run_oneway_density_stratified as runner


def _graph() -> nx.Graph:
    graph = nx.Graph()
    graph.add_node(1, lat=37.50, lon=127.00)
    graph.add_node(2, lat=37.51, lon=127.01)
    graph.add_edge(1, 2, length=1000, safety_score=0.5, accident_score=0.5, slope_score=0.5)
    return graph


def test_resolve_conditions_crosses_multiplier_waypoints_and_weight_modes():
    dataset = {
        "routes": [{
            "origin_id": "dense", "origin_label": "출발", "origin_density_tier": "dense",
            "origin_density": 30.0, "origin_lat": 37.50, "origin_lon": 127.00,
            "destination_id": "sparse", "destination_label": "도착",
            "destination_lat": 37.51, "destination_lon": 127.01,
        }],
        "detour_multipliers": [1.25, 1.5],
        "num_waypoints": [2, 3],
        "weight_conditions": {
            "distance": {"safety": 0.0, "comfort": 0.0},
            "safety": {"safety": 1.0, "comfort": 0.0},
        },
    }

    conditions = runner._resolve_conditions(dataset, _graph())

    assert len(conditions) == 8
    assert {condition["weight_mode"] for condition in conditions} == {"distance", "safety"}
    assert {condition["target_km"] for condition in conditions} == {1.25, 1.5}
    assert all(condition["shortest_distance_km"] == 1.0 for condition in conditions)


def test_stage_two_uses_the_fixed_ten_seed_set():
    assert runner._stage_seeds("1") == [runner.BENCHMARK_SEEDS[0]]
    assert runner._stage_seeds("2") == runner.BENCHMARK_SEEDS
    assert len(runner._stage_seeds("2")) == 10


@pytest.mark.parametrize(
    "weight_mode, safety, comfort, expected_alpha, expected_beta",
    [
        ("distance", 0.0, 0.0, None, None),
        ("safety", 1.0, 0.0, "positive", 0.0),
        ("comfort", 0.0, 1.0, 0.0, "positive"),
        ("mixed", 0.7, 0.7, "positive", "positive"),
    ],
)
def test_task_params_build_the_declared_weight_axis(
    monkeypatch, weight_mode, safety, comfort, expected_alpha, expected_beta,
):
    from src.route_engine.weighted_cost_runtime import attach_weighted_cost, prepare_weighted_cost

    graph = _graph()
    attach_weighted_cost(graph, prepare_weighted_cost(graph, enabled=True, coverage_min_ratio=0.95))
    monkeypatch.setattr(runner, "_POOL_GRAPH", graph)

    params = runner._task_params({
        "target_km": 1.25, "num_waypoints": 2, "weight_mode": weight_mode,
        "safety": safety, "comfort": comfort,
    }, seed=42)
    context = params["cost_context"]

    if expected_alpha is None:
        assert context is None
        assert params["preference_metrics_context"] is not None
        return
    assert (context.alpha > 0) if expected_alpha == "positive" else context.alpha == expected_alpha
    assert (context.beta > 0) if expected_beta == "positive" else context.beta == expected_beta


def test_oneway_condition_columns_keep_density_destination_multiplier_and_weight_separate():
    import pandas as pd

    frame = pd.DataFrame([{
        "algorithm": "GRASP", "seed": 42, "origin_id": "a", "destination_id": "b",
        "origin_density_tier": "dense", "shortest_distance_km": 1.0,
        "detour_multiplier": 1.25, "weight_mode": "safety", "target_km": 1.25,
    }])
    columns = aggregate_results.condition_columns(frame)

    for expected in ("origin_id", "destination_id", "origin_density_tier", "shortest_distance_km", "detour_multiplier", "weight_mode"):
        assert expected in columns


def test_runner_writes_the_weight_directionality_summary(tmp_path):
    rows = [
        {
            "algorithm": "GRASP", "status": "ok", "seed": 42, "mode": "oneway",
            "origin_id": "a", "destination_id": "b", "origin_density_tier": "dense",
            "shortest_distance_km": 1.0, "detour_multiplier": 1.25, "target_km": 1.25,
            "num_waypoints": 2, "weight_mode": "distance", "route_signature": "base",
            "safety_exposure_ratio": 0.6, "comfort_exposure_ratio": 0.4,
        },
        {
            "algorithm": "GRASP", "status": "ok", "seed": 42, "mode": "oneway",
            "origin_id": "a", "destination_id": "b", "origin_density_tier": "dense",
            "shortest_distance_km": 1.0, "detour_multiplier": 1.25, "target_km": 1.25,
            "num_waypoints": 2, "weight_mode": "safety", "route_signature": "safe",
            "cost_alpha": 0.7, "cost_beta": 0.0,
            "safety_exposure_ratio": 0.3, "comfort_exposure_ratio": 0.4,
            "safety_penalty_ratio": 0.21, "comfort_penalty_ratio": 0.0,
        },
    ]
    out_path = tmp_path / "oneway.csv"

    runner._write_aggregates(rows, out_path)

    assert out_path.with_name("oneway_aggregate_by_condition.csv").exists()
    assert out_path.with_name("oneway_aggregate_by_algorithm.csv").exists()
    assert out_path.with_name("oneway_aggregate_weight_directionality.csv").exists()
