"""Beam 어댑터가 실제 기록을 그대로 공통 이벤트로 옮기는지 확인한다.

핵심 질문은 둘이다 — "장면이 엔진이 실제로 한 일과 같은가"와 "없는 사실을 만들지
않는가". 그래서 반복마다 유지·탈락 후보가 확장 후보를 정확히 나누는지, 부모 후보가
실제로 접두사인지, 변환할 수 없는 기록에서 멈추는지를 본다.
"""

import sys
import types

import pytest

from visualizations import route_experiment
from visualizations.beam_adapter import DROP_PHASE, record_beam_trace
from visualizations.events import TraceMismatchError, validate_events
from visualizations.route_experiment import compare_recording, execute, graph_digest
from visualizations.route_story import prepare_story

BEAM_MODES = ("circular", "detour")


@pytest.fixture
def capture(monkeypatch):
    """어댑터에 들어간 원본 기록과 인자를 그대로 잡아 둔다."""
    box = {}
    original = route_experiment.record_beam_trace

    def spy(trace, **kwargs):
        box["events"] = [dict(event) for event in trace.events]
        box["kwargs"] = kwargs
        return original(trace, **kwargs)

    monkeypatch.setattr(route_experiment, "record_beam_trace", spy)
    return box


def _run(graph, mode, **options):
    start = {"node": 0, **graph.nodes[0]}
    end = start if mode == "circular" else {"node": 24, **graph.nodes[24]}
    target = None if mode == "shortest" else 1500
    return execute(graph, mode, start, end, target, **options), start, end


def _by_iteration(events, kind):
    return {event["values"]["iteration"]: event
            for event in events if event["kind"] == kind and "iteration" in event["values"]}


@pytest.mark.parametrize("mode", BEAM_MODES)
def test_trace_is_one_common_record_from_run_start_to_final(grid, mode):
    result, _, _ = _run(grid, mode)
    events = result["trace"]
    assert validate_events(events) is events
    assert events[0]["kind"] == "run_start"
    assert events[-1]["kind"] == "final"
    assert [event["seq"] for event in events] == list(range(len(events)))
    assert events[-1]["paths"] == result["paths"]
    assert {event["algorithm"] for event in events} == {"beam"}


@pytest.mark.parametrize("mode", BEAM_MODES)
def test_kept_and_dropped_candidates_split_the_expansion_exactly(grid, mode):
    result, _, _ = _run(grid, mode)
    events = result["trace"]
    candidates = [event for event in events if event["kind"] == "candidates"]
    assert len(candidates) == result["beam_iterations"]
    kept = _by_iteration(events, "select")
    dropped = _by_iteration(events, "reject")
    for event in candidates:
        iteration = event["values"]["iteration"]
        generated = {tuple(path) for path in event["paths"]}
        keeps = {tuple(path) for path in kept[iteration]["paths"]}
        drops = {tuple(path) for path in dropped.get(iteration, {"paths": []})["paths"]}
        assert keeps | drops == generated
        assert keeps & drops == set()
        assert len(keeps) == event["values"]["kept"]
    assert all(event["phase"] == DROP_PHASE for event in dropped.values())
    for event in (*kept.values(), *dropped.values()):
        assert event["decision"]["reason"]
        assert event["decision"]["accepted"] is (event["kind"] == "select")


@pytest.mark.parametrize("mode", BEAM_MODES)
def test_parent_candidate_id_points_at_a_real_prefix(grid, mode):
    result, _, _ = _run(grid, mode)
    nodes_by_id = {}
    for event in result["trace"]:
        if event["kind"] != "candidates":
            continue
        for path, identifier in zip(event["paths"], event["values"]["candidate_ids"]):
            nodes_by_id[identifier] = tuple(path)
    linked = 0
    for event in result["trace"]:
        ids = event.get("values", {}).get("candidate_ids")
        parents = event.get("values", {}).get("parent_candidate_ids")
        if not ids:
            continue
        for path, parent in zip(event["paths"], parents):
            if parent is None:
                continue
            prefix = nodes_by_id[parent]
            assert tuple(path[:len(prefix)]) == prefix
            assert len(prefix) < len(path)
            linked += 1
    assert linked, "최소 한 번은 부모 후보가 이어져야 합니다."


@pytest.mark.parametrize("mode", BEAM_MODES)
def test_cleanup_before_and_after_are_measured_by_route_story(grid, mode):
    result, _, _ = _run(grid, mode)
    prepare_story(grid, result)
    cleanups = [event for event in result["trace"] if event["kind"] == "cleanup"]
    assert cleanups
    for event in cleanups:
        assert event["before"]
        assert event["stage_metrics"] is not None
        assert event["before_metrics"] is not None
        removed = event["values"]["removed_nodes"]
        assert removed == len(event["before"]) - len(event["paths"][0])


def test_unknown_source_phase_stops_the_conversion(grid, capture):
    _run(grid, "circular")
    events = capture["events"]
    events.insert(1, {"phase": "guess", "paths": [], "accepted": True})
    with pytest.raises(TraceMismatchError, match="모르는 원본 phase"):
        record_beam_trace(types.SimpleNamespace(events=events), **capture["kwargs"])


def test_missing_key_in_a_known_phase_stops_the_conversion(grid, capture):
    _run(grid, "circular")
    events = capture["events"]
    first_expand = next(i for i, event in enumerate(events) if event["phase"] == "expand")
    events[first_expand] = {k: v for k, v in events[first_expand].items() if k != "kept"}
    with pytest.raises(TraceMismatchError, match="키가 없습니다"):
        record_beam_trace(types.SimpleNamespace(events=events), **capture["kwargs"])


@pytest.mark.parametrize("mode,expected", [("circular", "service"), ("detour", "service"),
                                           ("shortest", "service")])
def test_service_use_follows_the_service_engine_table(grid, mode, expected):
    result, _, _ = _run(grid, mode)
    assert result["conditions"]["service_use"] == expected


@pytest.mark.parametrize("mode", BEAM_MODES)
def test_recording_does_not_change_the_engine_result(grid, mode):
    before = graph_digest(grid)
    recorded, start, end = _run(grid, mode)
    plain, _, _ = _run(grid, mode, record=False)
    assert compare_recording(recorded, plain)
    assert graph_digest(grid) == before
    assert sys.gettrace() is None
    assert recorded["conditions"]["heuristic"]["name"] == "haversine"
    assert recorded["trace_source_hashes"], "settrace 구조 감지는 아직 남아 있어야 합니다."
