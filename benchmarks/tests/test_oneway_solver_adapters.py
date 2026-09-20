"""편도 엔진을 실제 벤치마크 registry로 연결하는 어댑터 회귀 테스트."""

import networkx as nx
import pytest

from benchmarks.benchmark import SEED_SENSITIVE_SOLVERS, SOLVER_REGISTRY
from benchmarks.results import validate_solver_result
from benchmarks.solvers.astar_solver import OnewayAstarSolver
from benchmarks.solvers.oneway_grasp_waypoint_alns_solver import OnewayGraspWaypointAlnsSolver
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.scoring.scoring_engine import WeightedEdgeCost


def _weighted_detour_graph() -> nx.Graph:
    """짧지만 위험한 직선과, 길지만 안전한 우회로를 가진 작은 그래프."""
    graph = nx.Graph()
    for node in range(6):
        graph.add_node(node, lat=37.5, lon=127.0)

    for path, length, safety, accident in (
        ([0, 1, 2, 3], 100.0, 0.0, 1.0),
        ([0, 4, 5, 3], 125.0, 1.0, 0.0),
    ):
        for start, end in zip(path, path[1:]):
            graph.add_edge(
                start, end, length=length, safety_score=safety,
                accident_score=accident, slope_score=1.0,
            )
    return graph


def _oneway_grid() -> nx.Graph:
    """서비스 엔진 단위 테스트와 같은 5x5 실제 도로형 격자."""
    lat0, lon0 = 37.5, 127.0
    lat_step, lon_step = 0.0015, 0.0018
    graph = nx.Graph()

    def node(row: int, col: int) -> int:
        return row * 5 + col + 1

    def coords(row: int, col: int) -> tuple[float, float]:
        return lat0 + row * lat_step, lon0 + col * lon_step

    for row in range(5):
        for col in range(5):
            lat, lon = coords(row, col)
            graph.add_node(node(row, col), lat=lat, lon=lon)
    for row in range(5):
        for col in range(5):
            if col < 4:
                a, b = node(row, col), node(row, col + 1)
                graph.add_edge(a, b, length=PathUtils._haversine_m(*coords(row, col), *coords(row, col + 1)))
            if row < 4:
                a, b = node(row, col), node(row + 1, col)
                graph.add_edge(a, b, length=PathUtils._haversine_m(*coords(row, col), *coords(row + 1, col)))
    return graph


def test_astar_adapter_passes_cost_context_to_the_engine():
    context = WeightedEdgeCost(0.5, 0.0, accident_ratio=0.5, weight_limit=1.0)

    result = OnewayAstarSolver().solve(
        _weighted_detour_graph(), 0, 3, {"target_km": 1.0, "cost_context": context},
    )

    assert result["paths"] == [[0, 4, 5, 3]]
    assert result["cost"] == pytest.approx(375.0)
    assert result["baseline_shortest_km"] == pytest.approx(0.3)
    assert result["baseline_shortest_overlap_ratio"] == 0.0


def test_oneway_grasp_alns_adapter_runs_the_service_engine_and_is_registered():
    graph = _oneway_grid()
    start, end = 1, 25
    direct_m = PathUtils._haversine_m(37.5, 127.0, 37.5 + 4 * 0.0015, 127.0 + 4 * 0.0018)

    solver = SOLVER_REGISTRY["oneway-grasp-wp-alns"]
    assert isinstance(solver, OnewayGraspWaypointAlnsSolver)
    assert "oneway-grasp-wp-alns" in SEED_SENSITIVE_SOLVERS

    result = solver.solve(graph, start, end, {"target_km": direct_m * 1.5 / 1000, "seed": 42})

    path = result["paths"][0]
    assert path[0] == start
    assert path[-1] == end
    assert result["cost"] > 0
    assert result["baseline_shortest_km"] is not None
    assert result["baseline_shortest_overlap_ratio"] is not None
    assert result["selection_status"] in {"feasible", "fallback_distance"}
    assert result["alns_operator_stats"] is not None
    assert "candidate_paths" not in result
    assert validate_solver_result(result)["paths"] == [path]
