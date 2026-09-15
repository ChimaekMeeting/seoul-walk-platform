"""GRASP·경유지 어댑터가 실제 기록만으로 공통 이벤트를 만드는지 확인한다.

특히 두 가지를 지킨다.

1. **내부 수락과 최종 채택을 섞지 않는다** — `alns_accept`는 절대 `select`/`reject`가
   되지 않고, 실제 채택 판단인 `alns_result`·`vns_decision`만 기록된 `accepted`를 따른다.
2. **수치를 지어내지 않는다** — 변환 전후 이벤트를 1:1(경유지 선택만 1:2)로 짝지어,
   공통 `values`의 숫자가 원본 이벤트의 숫자이거나 원본이 담은 리스트 길이(또는 두 길이의
   차)에서 바로 나온 값인지 확인한다.
"""

import sys
import types
from itertools import product

import pytest

from visualizations import route_experiment
from visualizations.events import TraceMismatchError, validate_events
from visualizations.route_experiment import compare_recording, execute, graph_digest
from visualizations.waypoint_adapter import record_waypoint_trace

REFINEMENTS = ("none", "local", "vnd", "vns", "alns")
GRASP_ITERATIONS = 2
SEED = 42
# 한 원본 이벤트가 만드는 공통 이벤트 수. 경유지 선택만 candidates + select 두 장면이다.
FANOUT = {"grasp_choice": 2}


@pytest.fixture
def capture(monkeypatch):
    """어댑터에 들어간 원본 기록과 인자를 그대로 잡아 둔다."""
    box = {}
    original = route_experiment.record_waypoint_trace

    def spy(trace, **kwargs):
        box["events"] = [dict(event) for event in trace.events]
        box["kwargs"] = kwargs
        return original(trace, **kwargs)

    monkeypatch.setattr(route_experiment, "record_waypoint_trace", spy)
    return box


def _run(graph, refinement, **options):
    start = {"node": 0, **graph.nodes[0]}
    return execute(graph, f"grasp_{refinement}", start, start, 1500,
                   grasp_iterations=GRASP_ITERATIONS, seed=SEED, **options)


def _collect(value, numbers, lengths):
    """기록 안의 모든 숫자와 리스트 길이를 모은다(bool은 숫자로 세지 않는다)."""
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        numbers.add(float(value))
    elif isinstance(value, dict):
        for item in value.values():
            _collect(item, numbers, lengths)
    elif isinstance(value, (list, tuple)):
        lengths.add(float(len(value)))
        for item in value:
            _collect(item, numbers, lengths)


def _allowed_numbers(original):
    numbers, lengths = set(), set()
    _collect({k: v for k, v in original.items() if k != "phase"}, numbers, lengths)
    return numbers | lengths | {a - b for a, b in product(lengths, lengths)}


def _value_numbers(event):
    numbers, lengths = set(), set()
    _collect(event.get("values", {}), numbers, lengths)
    return numbers


def _pairs(originals, events):
    """원본 이벤트와 그것이 만든 공통 이벤트를 순서대로 짝짓는다."""
    converted = [event for event in events if "source_phase" in event]
    matched, cursor = [], 0
    for original in originals:
        group = converted[cursor:cursor + FANOUT.get(original["phase"], 1)]
        assert group, f"{original['phase']} 기록이 변환되지 않았습니다."
        assert {event["source_phase"] for event in group} == {original["phase"]}
        matched.append((original, group))
        cursor += len(group)
    assert cursor == len(converted), "원본에 없는 공통 이벤트가 있습니다."
    return matched


@pytest.mark.parametrize("refinement", REFINEMENTS)
def test_trace_is_one_common_record_from_run_start_to_final(grid, refinement):
    result = _run(grid, refinement)
    events = result["trace"]
    assert validate_events(events) is events
    assert events[0]["kind"] == "run_start"
    assert events[-1]["kind"] == "final"
    assert [event["seq"] for event in events] == list(range(len(events)))
    assert {event["algorithm"] for event in events} == {"grasp"}
    assert events[0]["values"]["seed"] == SEED
    assert events[0]["values"]["grasp_iters"] == GRASP_ITERATIONS


def test_internal_alns_acceptance_never_becomes_a_final_choice(grid):
    events = _run(grid, "alns")["trace"]
    internal = [event for event in events if event["phase"] == "alns_accept"]
    assert internal, "ALNS 실행에는 내부 수락 판단이 있어야 합니다."
    for event in internal:
        assert event["kind"] == "evaluate"
        assert "decision" not in event
        assert isinstance(event["values"]["accepted"], bool)
    results = [event for event in events if event["phase"] == "alns_result"]
    assert results
    for event in results:
        assert event["kind"] == ("select" if event["accepted"] else "reject")
        assert event["decision"]["accepted"] is bool(event["accepted"])


def test_vns_decisions_and_winner_follow_the_recorded_flag(grid):
    events = _run(grid, "vns")["trace"]
    decisions = [event for event in events if event["phase"] == "vns_decision"]
    assert decisions
    for event in decisions:
        assert event["kind"] == ("select" if event["accepted"] else "reject")
    winners = [event for event in events if event["phase"] == "winner"]
    assert winners
    for event in winners:
        assert event["kind"] == "select"
        assert "전체 최선 갱신" in event["decision"]["reason"]


@pytest.mark.parametrize("refinement", REFINEMENTS)
def test_waypoint_ids_and_road_paths_are_never_mixed(grid, refinement):
    events = _run(grid, refinement)["trace"]
    for event in events:
        for path in event["paths"]:
            # 도로 노드열은 반드시 실제 간선으로 이어진다. 경유지 ID 목록은 그렇지 않다.
            assert all(grid.has_edge(u, v) for u, v in zip(path, path[1:]))
        if event["phase"] in ("grasp_choice", "destroy", "repair", "alns_accept"):
            assert event["paths"] == [], "경유지 단계에는 도로 경로가 없습니다."
        if "waypoints" in event and event["phase"] not in ("grasp_choice",):
            assert event["nodes"] == event["waypoints"]


@pytest.mark.parametrize("refinement", REFINEMENTS)
def test_decisions_are_explained_and_values_are_never_invented(grid, refinement, capture):
    events = _run(grid, refinement)["trace"]
    for original, group in _pairs(capture["events"], events):
        allowed = _allowed_numbers(original)
        for event in group:
            if "decision" in event:
                assert event["decision"]["reason"].strip()
            unknown = _value_numbers(event) - allowed
            assert not unknown, f"{event['phase']}의 values에 원본에 없는 수치 {unknown}"


def test_unknown_source_phase_stops_the_conversion(grid, capture):
    _run(grid, "alns")
    events = capture["events"]
    events.insert(1, {"phase": "guess", "paths": [], "accepted": True})
    with pytest.raises(TraceMismatchError, match="모르는 원본 phase"):
        record_waypoint_trace(types.SimpleNamespace(events=events), **capture["kwargs"])


def test_missing_key_in_a_known_phase_stops_the_conversion(grid, capture):
    _run(grid, "none")
    events = capture["events"]
    index = next(i for i, event in enumerate(events) if event["phase"] == "constructed")
    events[index] = {k: v for k, v in events[index].items() if k != "construction_call"}
    with pytest.raises(TraceMismatchError, match="키가 없습니다"):
        record_waypoint_trace(types.SimpleNamespace(events=events), **capture["kwargs"])


@pytest.mark.parametrize("refinement", REFINEMENTS)
def test_grasp_engines_are_marked_benchmark_only(grid, refinement):
    conditions = _run(grid, refinement)["conditions"]
    assert conditions["service_use"] == "benchmark_only"
    assert conditions["algorithm"] == "grasp"
    assert conditions["heuristic"]["name"] == "haversine"


@pytest.mark.parametrize("refinement", REFINEMENTS)
def test_candidate_ids_hang_off_the_restart_root(grid, refinement):
    events = _run(grid, refinement)["trace"]
    roots = {event["candidate_id"] for event in events
             if event.get("candidate_id", "").count(":") == 1}
    assert roots, "재시작 뿌리 후보가 있어야 합니다."
    for event in events:
        parent = event.get("parent_candidate_id")
        if parent is None:
            continue
        assert parent in roots
        assert event["candidate_id"].startswith(f"{parent}:")


@pytest.mark.parametrize("refinement", REFINEMENTS)
def test_recording_does_not_change_the_engine_result(grid, refinement):
    before = graph_digest(grid)
    recorded = _run(grid, refinement)
    plain = _run(grid, refinement, record=False)
    assert compare_recording(recorded, plain)
    assert graph_digest(grid) == before
    assert sys.gettrace() is None
    assert recorded["trace_source_hashes"], "settrace 구조 감지는 아직 남아 있어야 합니다."
