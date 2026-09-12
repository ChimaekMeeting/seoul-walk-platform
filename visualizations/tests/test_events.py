"""공통 이벤트 형식 검사가 잘못된 기록을 실제로 막는지 확인한다.

어댑터가 형식을 어기면 화면은 조용히 이상한 장면을 그린다. 그래서 어긋난 기록은
ValueError로 멈춰야 한다.
"""

import pytest

from visualizations.events import RunConditions, HeuristicConditions, validate_events


def _select(seq, **extra):
    return {"seq": seq, "kind": "select", "algorithm": "astar", "phase": "astar",
            "paths": [[1, 2]], **extra}


def _record(*middle):
    """run_start … final 로 감싼 최소 기록. middle은 seq 1부터 붙는다."""
    events = [{"seq": 0, "kind": "run_start", "algorithm": "astar", "phase": "start",
               "paths": [[1]]}]
    events += list(middle)
    events.append({"seq": len(events), "kind": "final", "algorithm": "astar",
                   "phase": "final", "paths": [[1, 2]]})
    return events


def test_minimal_record_passes_and_is_returned_unchanged():
    events = _record(_select(1, values={"g_m": 1.0, "frontier_top": [{"node": 2, "f_m": 3.0}]},
                             decision={"accepted": True, "reason": "f가 가장 작아 선택"},
                             focus={"nodes": [2]}, current=2, frontier=[3, 4]))
    assert validate_events(events) is events


@pytest.mark.parametrize("missing", ["seq", "kind", "algorithm", "phase", "paths"])
def test_missing_required_key_is_rejected(missing):
    events = _record(_select(1))
    events[1].pop(missing)
    with pytest.raises(ValueError, match="필수 키가 없습니다"):
        validate_events(events)


def test_seq_must_be_continuous():
    events = _record(_select(1), _select(3))
    with pytest.raises(ValueError, match="seq는 0부터 1씩"):
        validate_events(events)


def test_unknown_kind_is_rejected():
    events = _record(_select(1))
    events[1]["kind"] = "expand"
    with pytest.raises(ValueError, match="모르는 kind"):
        validate_events(events)


@pytest.mark.parametrize("bad", [
    {"queue": {1, 2}},                      # 집합 같은 객체
    {"engine": object()},                   # 임의 객체
    {"nested": {"g_m": 1}},                 # values 최상위의 dict
    {"rows": [{"node": {1: 2}}]},           # 리스트 안 dict의 값이 또 dict
    {"h_m": float("inf")},                  # JSON으로 나갈 수 없는 수
])
def test_values_must_be_displayable(bad):
    events = _record(_select(1, values=bad))
    with pytest.raises(ValueError):
        validate_events(events)


def test_decision_needs_accepted_and_real_reason():
    events = _record(_select(1, decision={"accepted": True}))
    with pytest.raises(ValueError, match="decision에 reason"):
        validate_events(events)
    events = _record(_select(1, decision={"accepted": True, "reason": "  "}))
    with pytest.raises(ValueError, match="decision\\['reason'\\]"):
        validate_events(events)


def test_focus_needs_node_list():
    events = _record(_select(1, focus={"node": 3}))
    with pytest.raises(ValueError, match="focus에는 리스트 nodes"):
        validate_events(events)


def test_record_must_start_with_run_start_and_end_with_final():
    events = _record(_select(1))
    events[0]["kind"] = "select"
    with pytest.raises(ValueError, match="run_start로 시작"):
        validate_events(events)
    events = _record(_select(1))
    events[-1]["kind"] = "select"
    with pytest.raises(ValueError, match="final로 끝나야"):
        validate_events(events)


def test_empty_record_is_rejected():
    with pytest.raises(ValueError, match="비어 있습니다"):
        validate_events([])


def test_run_conditions_serialize_to_plain_dict():
    conditions = RunConditions(
        algorithm="astar", engine_class="OnewayAstarEngine", mode="shortest_alt",
        heuristic=HeuristicConditions(name="alt_planar", method="planar", k_requested=8,
                                      k_actual=8, seed=0, landmarks=[{"node": 1, "lat": 37.0, "lon": 127.0}]),
        weight_policy="기본 엣지 비용 = length", service_use="service",
        target_m=None, seed=42, config={"alt_k": 8})
    data = conditions.as_dict()
    assert data["heuristic"]["landmarks"][0]["node"] == 1
    assert data["artifact"] == {"data_version": None, "sha256": None}
    assert data["service_use"] == "service"
