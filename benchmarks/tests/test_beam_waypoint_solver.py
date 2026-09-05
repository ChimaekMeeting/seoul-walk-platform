"""
benchmarks/tests/test_beam_waypoint_solver.py

CircularBeamWaypointSolver가 beam_search()의 순수 거리전용 결과를
waypoint_local_search.py::local_search()(GRASP-Waypoint+Local 엔진과 동일) 1패스로
실제로 교정하는지 검증한다(2026-09-06, "Beam 재통행 인식 평가" 재설계).

작은 합성 그래프(삼각형 S-A-B + S에 매달린 막다른 가지 C)를 쓴다:
    S-A=1000m, A-B=1000m, B-S=1000m (삼각형, 두 경유지(A,B)를 고르면 재통행 0%)
    S-C=550m (막다른 가지 — C를 낀 조합은 항상 S를 다시 거쳐야 해서 재통행 정확히 50%)

target_km=3.1(=3100m)은 2*550 + 2*1000 = 3100으로 맞춰, C를 낀 조합(예: A,C)의 목표거리
오차가 정확히 0m가 되게 설계했다 — 순수 거리 랭킹이라면 오차 100m인 삼각형(A,B)보다
이 조합이 항상 이긴다. beam_width=1로 좁혀 beam_search() 혼자서는 (A,B)가 최종 결과에
아예 살아남지 못하게 만든 뒤(pool_size=3, num_waypoints=2 기본값 기준 손으로 검증:
2026-09-06), 그 뒤에 붙는 지역개선 1패스가 (A,B)를 이웃으로 찾아 되돌리는지 본다.
"""

import networkx as nx
import pytest

from benchmarks.solvers.beam_waypoint_solver import CircularBeamWaypointSolver

_START, _A, _B, _C = 0, 1, 2, 3


def _build_graph() -> nx.Graph:
    graph = nx.Graph()
    graph.add_node(_START, lat=37.5000, lon=127.0000)
    graph.add_node(_A, lat=37.5010, lon=127.0000)
    graph.add_node(_B, lat=37.4990, lon=127.0000)
    graph.add_node(_C, lat=37.5000, lon=127.0050)
    graph.add_edge(_START, _A, length=1000.0)
    graph.add_edge(_A, _B, length=1000.0)
    graph.add_edge(_B, _START, length=1000.0)
    graph.add_edge(_START, _C, length=550.0)
    return graph


def test_local_search_pass_recovers_clean_loop_after_narrow_beam():
    graph = _build_graph()
    solver = CircularBeamWaypointSolver()

    result = solver.solve(
        graph, start_node=_START, target_node=_START,
        params={"target_km": 3.1, "beam_width": 1},
    )

    assert result["selection_status"] == "feasible"
    assert result["repeated_edge_ratio"] == pytest.approx(0.0)
    assert result["cost"] == pytest.approx(3000.0)
    assert set(result["paths"][0]) == {_START, _A, _B}
