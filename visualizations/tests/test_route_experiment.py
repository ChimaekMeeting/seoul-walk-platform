"""실제 엔진 계측의 결과 보존과 실험 입력 경계를 검증한다."""

import sys

import networkx as nx
import pytest

from src.route_engine.engines import circular_beam, oneway_beam
from visualizations.route_experiment import compare_recording, execute, graph_digest, validate_lengths
from visualizations.route_trace import SearchTrace
from visualizations.routes import validate_destination


@pytest.mark.parametrize("mode", ["shortest", "detour", "circular"])
def test_real_engine_trace_preserves_paths_graph_and_score_functions(grid, mode):
    before = graph_digest(grid)
    original = (circular_beam.calculate_custom_score, oneway_beam.calculate_custom_score)
    start = {"node": 0, **grid.nodes[0]}
    end = start if mode == "circular" else {"node": 24, **grid.nodes[24]}
    target = None if mode == "shortest" else 1500
    recorded = execute(grid, mode, start, end, target)
    plain = execute(grid, mode, start, end, target, record=False)
    assert compare_recording(recorded, plain)
    assert recorded["run_seconds"] is None
    assert plain["run_seconds"] > 0
    assert graph_digest(grid) == before
    assert sys.gettrace() is None
    assert original == (circular_beam.calculate_custom_score, oneway_beam.calculate_custom_score)
    phases = {e["phase"] for e in recorded["trace"]}
    if mode == "shortest":
        # A*는 어댑터가 run_start·select·final을 한 기록으로 만든다(중복 삽입 없음).
        assert {"start", "astar", "final"} <= phases
        assert [e["seq"] for e in recorded["trace"]] == list(range(len(recorded["trace"])))
        assert recorded["conditions"]["heuristic"]["name"] == "haversine"
        assert recorded["trace_source_hashes"] == {}
        assert recorded["metrics"][0]["distance_m"] == nx.dijkstra_path_length(grid, 0, 24, weight="length")
        assert recorded["metrics"][0]["endpoints_match"]
    else:
        assert {"expand", "keep", "connect", "selection", "prune", "final"} <= phases
        for event in recorded["trace"]:
            if event["phase"] == "keep":
                assert len(event["paths"]) == event["kept"] <= 8
                assert event["generated"] >= event["kept"]
                for path in event["paths"]:
                    assert len(path) == len(set(path))
                    assert all(grid.has_edge(u, v) for u, v in zip(path, path[1:]))


def test_trace_restored_when_run_raises(grid):
    from src.schema.route_schema import CircularRouteInput
    engine = circular_beam.CircularBeamEngine(CircularRouteInput(start_lat=37, start_lon=127), grid)
    with pytest.raises(RuntimeError, match="test failure"):
        with SearchTrace(engine):
            raise RuntimeError("test failure")
    assert sys.gettrace() is None


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf"), None])
def test_invalid_distance_data_is_rejected(grid, bad):
    if bad is None:
        grid[0][1].pop("length")
    else:
        grid[0][1]["length"] = bad
    with pytest.raises(ValueError, match="length"):
        validate_lengths(grid)


@pytest.mark.parametrize("changes", [{"lat": float("nan")}, {"lon": 181},
    {"coordinate_source_url": ""}, {"coordinate_source_url": "file:///local"},
    {"verified_date": "2026-02-30"}, {"verified_date": "20260910"}])
def test_destination_provenance_and_coordinates(changes):
    location = {"lat": 37.5762348, "lon": 126.9726844,
                "coordinate_source_url": "https://www.openstreetmap.org/node/3403538914",
                "verified_date": "2026-09-10"}
    location.update(changes)
    with pytest.raises(ValueError, match="destination"):
        validate_destination(location)


@pytest.mark.parametrize("refinement", ["none", "local", "vnd", "vns", "alns"])
def test_waypoint_recording_preserves_real_engine_and_reports_own_tolerance(grid, refinement):
    start = {"node": 0, **grid.nodes[0]}
    before = graph_digest(grid)
    recorded = execute(grid, f"grasp_{refinement}", start, start, 1500, grasp_iterations=2)
    plain = execute(grid, f"grasp_{refinement}", start, start, 1500, record=False, grasp_iterations=2)
    assert compare_recording(recorded, plain)
    assert graph_digest(grid) == before
    assert sys.gettrace() is None
    assert recorded["tolerance_ratio"] == .05
    phases = {e["phase"] for e in recorded["trace"]}
    assert {"grasp_choice", "constructed", "winner", "final"} <= phases
    if refinement != "vns":
        # 어댑터가 선택 1회를 candidates(RCL) + select(실제 선택) 두 장면으로 나누므로
        # 원본 선택 횟수는 candidates 쪽만 센다.
        choices = [e for e in recorded["trace"]
                   if e["phase"] == "grasp_choice" and e["kind"] == "candidates"]
        assert len(choices) <= 2 * 2  # 재시작 2회 × 경유지 2개: 삼항식 재진입 중복 방지
        completions = [e for e in recorded["trace"] if e["phase"] in ("constructed", "construction_failed")]
        assert len(completions) == 2
    if refinement in ("local", "vnd", "vns"):
        assert "neighbor" in phases
    if refinement == "vns":
        assert "shake" in phases
        assert "vns_decision" in phases
    if refinement == "alns":
        assert {"destroy", "repair", "alns_result"} <= phases
        decisions = [e for e in recorded["trace"] if e["phase"] == "alns_accept"]
        for decision in decisions:
            assert decision["internal_after"]["error_m"] - decision["internal_before"]["error_m"] == pytest.approx(decision["delta"])
        # 내부 판단/실제 재검증 다음에 같은 초기 후보의 정제 완료를 표시한다.
        steps = [e["phase"] for e in recorded["trace"]]
        for i, phase in enumerate(steps):
            if phase == "alns_result":
                assert steps[i+1] == "refinement_done"
    assert "refinement_done" in phases
    for event in recorded["trace"]:
        if event["phase"] == "improved":
            assert event["before"]
            assert event["accepted"]
            assert event["decision_reason"]
    for event in recorded["trace"]:
        for path in event["paths"]:
            assert all(grid.has_edge(u, v) for u, v in zip(path, path[1:]))


def test_astar_records_every_pop_with_real_parent_edges(grid):
    start, end = {"node": 0, **grid.nodes[0]}, {"node": 24, **grid.nodes[24]}
    result = execute(grid, "shortest", start, end)
    events = [e for e in result["trace"] if e["phase"] == "astar"]
    assert len(events) == result["astar_queue_pops"]
    for event in events:
        assert event["kind"] == "select"
        assert all(grid.has_edge(u, v) for u, v in event["tree"])
        assert event["paths"][0][0] == start["node"]
        assert event["paths"][0][-1] == event["current"]
