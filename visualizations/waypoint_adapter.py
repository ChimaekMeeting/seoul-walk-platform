"""GRASP·경유지 계열 기록을 공통 이벤트로 바꾸는 어댑터.

입력은 현재 settrace 수집물(`waypoint_trace.WaypointTrace`, 오프라인 전용)이며, 엔진
훅이 승인되면 입력만 바뀐다 — 이 어댑터와 `events.py`는 그대로 남는다. 훅 제안은
`docs/proposals/route_engine_trace_observer_proposal.md`에 있다.

## 매핑

| 원본 phase | kind | 비고 |
|---|---|---|
| (없음) | `run_start` | 어댑터가 만든다. seed·재시작 수·경유지 수·정제 방식 |
| `grasp_choice` | `candidates` + `select` | 제한 후보 목록(RCL)과 실제 선택을 나눈다 |
| `constructed` | `route_changed` | 경유지를 도로 경로로 연결한 초기 후보 |
| `construction_failed` | `reject` | 구간 연결 실패 |
| `neighbor` | `evaluate` | 검토만 한 이웃 후보(5개마다 표본) |
| `improved` | `route_changed` | 현재 경로를 실제로 바꾼 개선 |
| `refinement_done` | `evaluate` | 한 초기 후보의 개선 종료. 채택 판단은 `winner` |
| `winner` | `select` | 전체 최선 갱신 |
| `shake` | `route_changed` | VNS 교란(개선 전) |
| `shake_failed` | `reject` | 교란 후보 생성 실패 |
| `vns_decision` | `select`/`reject` | 기록된 `accepted`에 따름 |
| `destroy`·`repair` | `candidates` | ALNS 연산자. 경유지 순서만 바꾼 상태 |
| `alns_accept` | `evaluate` | **내부** 수락. 최종 채택이 아니다 |
| `alns_result` | `select`/`reject` | 도로 경로 재검증 결과 |
| `prune` | `cleanup` | 기존 정리 규칙 전후 |
| (없음) | `final` | 엔진이 반환한 경로 |

## 내부 수락과 최종 채택을 섞지 않는다

`alns_accept`는 ALNS 내부 비용·온도 규칙의 판단이라 나쁜 후보도 일시적으로 받아들인다.
그래서 `evaluate`로만 남기고 `select`/`reject`로 올리지 않는다. 실제로 경로에 반영되는
판단은 도로 경로로 다시 연결해 비교한 `alns_result`다. 화면과 문서에서도 이 둘을 다른
문구로 설명한다.

## 경유지와 도로 경로

`nodes`에는 경유지 ID만, `paths`에는 도로 노드열만 넣는다. 섞으면 화면이 경유지 순서
점선과 실제 경로를 구분하지 못한다.

## candidate_id

재시작(구축 호출) 단위 `restart:{n}`이 뿌리다. `n`은 원본 기록의 `construction_call`
(구축 함수 호출 순번)이며, VNS 내부 재구축도 이 번호를 올린다. 정제 단계 이벤트는 그
뿌리를 `parent_candidate_id`로 갖고, VNS·ALNS 내부 후보는 `restart:{n}:vns:{k}` ·
`restart:{n}:alns:{k}`를 쓴다. 이웃 검토는 그 아래 `:nb:{검토 순번}`이다.
"""

from __future__ import annotations

import math

from visualizations.events import (
    ArtifactRef,
    HeuristicConditions,
    RunConditions,
    TraceMismatchError,
    service_use_for,
    validate_events,
)

ALGORITHM = "grasp"

_WINNER_REASON = "전체 최선 갱신(RouteObjective 비교)."
_CHOICE_REASON = "제한 후보 목록(RCL) 안에서 무작위로 선택"
_CONSTRUCTION_FAILED_REASON = "구간 연결 실패로 구축 실패"
_SHAKE_FAILED_REASON = "교란 후보 생성 실패"
_SHAKE_NOTE = "교란(VND 개선 전)"
_FINAL_REASON = "엔진 run()이 반환한 경로입니다."


def _finite(value):
    """`inf`(_INFEASIBLE의 distance_error_m 등)는 화면에 못 쓰므로 None으로 남긴다."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value if math.isfinite(float(value)) else None
    return value


def _flatten(event, key, out):
    """`{"distance_m": .., "error_m": ..}`처럼 한 겹 dict를 values 최상위로 편다.

    values 최상위에는 dict를 담을 수 없다(`events.py`). 값은 원본 기록의 숫자를 그대로
    옮기고 이름만 `{key}_{하위 키}`로 바꾼다 — 새로 계산하지 않는다.
    """
    data = event.get(key)
    if not isinstance(data, dict):
        return
    for name, value in data.items():
        out[f"{key}_{name}"] = _finite(value)


def _require(event, *keys):
    missing = [key for key in keys if key not in event]
    if missing:
        raise TraceMismatchError(
            f"원본 {event.get('phase')!r} 이벤트에 {', '.join(missing)} 키가 없습니다. "
            "변환할 수 없는 기록은 건너뛰지 않고 중단합니다."
        )
    return [event[key] for key in keys]


def _reason(event):
    (reason,) = _require(event, "decision_reason")
    if not isinstance(reason, str) or not reason.strip():
        raise TraceMismatchError(
            f"원본 {event.get('phase')!r} 이벤트의 decision_reason이 비어 있습니다."
        )
    return reason


def _weight_policy(config):
    ratio = getattr(config, "distance_tolerance_ratio", None)
    return (
        "구간 연결 비용 = length(EdgeCost mode='distance'). 경유지 사이 연결은 "
        "PathUtils.astar_path의 Haversine A*이며 ALT가 아니다. "
        f"최종 평가 허용 오차 비율 {ratio}, 기존 정리 규칙(prune_dead_ends) 유지."
    )


class _WaypointEvents:
    """원본 기록을 순서대로 읽어 공통 이벤트를 쌓는다."""

    def __init__(self, *, engine, start_node, end_node, config):
        self.start_node = start_node
        self.end_node = end_node
        self.events = []
        self.restart = 0           # 마지막으로 끝난 구축 호출 번호
        self.pending_call = None   # 진행 중인 구축 호출 번호(경유지 선택 단계)
        self.vns_index = 0
        self.alns_index = 0
        self.active = None         # 지금 열려 있는 VNS·ALNS 하위 후보 id
        self._append({
            "kind": "run_start",
            "phase": "start",
            "paths": [[start_node]],
            "nodes": [start_node, end_node],
            "values": {"seed": engine.seed, "grasp_iters": config.grasp_iters,
                       "num_waypoints": config.num_waypoints, "refinement": engine.refinement},
            "focus": {"nodes": [start_node, end_node]},
        })

    # ── id 규칙 ────────────────────────────────────────────────
    @property
    def root(self):
        """지금 다루고 있는 재시작(구축 호출)의 후보 id.

        경유지를 고르는 중이면 진행 중인 호출 번호, 그 밖에는 마지막으로 끝난 구축
        호출 번호를 쓴다 — 정제 단계 이벤트는 방금 만든 후보를 개선하는 것이므로.
        """
        return f"restart:{self.pending_call or self.restart}"

    def _current(self):
        """정제 단계 이벤트가 달릴 후보 id. 하위 후보가 열려 있으면 그것을 쓴다."""
        return self.active or self.root

    def _link(self, candidate_id):
        """공통 키 candidate_id·parent_candidate_id 한 쌍."""
        link = {"candidate_id": candidate_id}
        if candidate_id != self.root:
            link["parent_candidate_id"] = self.root
        return link

    def _append(self, event, source_phase=None):
        event = {"seq": len(self.events), "algorithm": ALGORITHM, **event}
        if source_phase is not None:
            event["source_phase"] = source_phase
        self.events.append(event)

    def _passthrough(self, event, keys=("waypoints", "previous_waypoints", "before",
                                        "current", "choices", "distance_m", "accepted",
                                        "decision_reason", "shake_level", "operator",
                                        "neighborhood", "examined", "changed", "delta",
                                        "temperature", "internal_before", "internal_after",
                                        "objective_before", "objective_after",
                                        "construction_call")):
        """기존 화면이 그대로 읽는 원본 키를 옮긴다. 값은 바꾸지 않는다."""
        return {key: event[key] for key in keys if key in event}

    # ── 원본 phase별 변환 ──────────────────────────────────────
    def grasp_choice(self, event):
        choices, current = _require(event, "choices", "current")
        if self.pending_call is None:
            self.pending_call = self.restart + 1
        base = self._passthrough(event)
        self._append({
            "kind": "candidates",
            "phase": "grasp_choice",
            "paths": [],
            "nodes": list(choices),
            "values": {"rcl_size": len(choices)},
            **self._link(self.root),
            **base,
        }, source_phase="grasp_choice")
        # 선택 장면에서는 RCL 점을 다시 그리지 않는다(원본 choices 키를 넘기지 않음).
        self._append({
            "kind": "select",
            "phase": "grasp_choice",
            "paths": [],
            "nodes": [current],
            "values": {"chosen": current},
            "decision": {"accepted": True, "reason": _CHOICE_REASON},
            **self._link(self.root),
            **{k: v for k, v in base.items() if k != "choices"},
        }, source_phase="grasp_choice")

    def constructed(self, event):
        (call,) = _require(event, "construction_call")
        paths = [list(path) for path in event["paths"]]
        self._append({
            "kind": "route_changed",
            "phase": "constructed",
            "paths": paths,
            "nodes": list(event.get("waypoints", [])),
            "values": {"distance_m": _finite(event.get("distance_m"))},
            "focus": {"nodes": list(paths[0]) if paths else []},
            **self._link(f"restart:{call}"),
            **self._passthrough(event),
        }, source_phase="constructed")
        self._finish_construction(call)

    def construction_failed(self, event):
        (call,) = _require(event, "construction_call")
        self._append({
            "kind": "reject",
            "phase": "construction_failed",
            "paths": [],
            "nodes": list(event.get("waypoints", [])),
            "decision": {"accepted": False, "reason": _CONSTRUCTION_FAILED_REASON},
            **self._link(f"restart:{call}"),
            **self._passthrough(event),
        }, source_phase="construction_failed")
        self._finish_construction(call)

    def neighbor(self, event):
        (examined,) = _require(event, "examined")
        values = {"sampled": True, "examined": examined,
                  "distance_m": _finite(event.get("distance_m"))}
        if "neighborhood" in event:
            values["neighborhood"] = event["neighborhood"]
        self._append({
            "kind": "evaluate",
            "phase": "neighbor",
            "paths": [list(path) for path in event["paths"]],
            "nodes": list(event.get("waypoints", [])),
            "values": values,
            **self._link(f"{self._current()}:nb:{examined}"),
            **self._passthrough(event),
        }, source_phase="neighbor")

    def improved(self, event):
        values = {"distance_m": _finite(event.get("distance_m"))}
        _flatten(event, "objective_before", values)
        _flatten(event, "objective_after", values)
        self._append({
            "kind": "route_changed",
            "phase": "improved",
            "paths": [list(path) for path in event["paths"]],
            "nodes": list(event.get("waypoints", [])),
            "values": values,
            "decision": {"accepted": True, "reason": _reason(event)},
            **self._link(self._current()),
            **self._passthrough(event),
        }, source_phase="improved")

    def refinement_done(self, event):
        (before,) = _require(event, "before")
        after = list(event["paths"][0]) if event["paths"] else []
        values = {"distance_m": _finite(event.get("distance_m")),
                  "changed": bool(event.get("changed")),
                  "nodes_before": len(before), "nodes_after": len(after)}
        # 조립 계층의 채택 판단은 winner가 한다. 여기에는 decision을 달지 않는다.
        self._append({
            "kind": "evaluate",
            "phase": "refinement_done",
            "paths": [list(path) for path in event["paths"]],
            "nodes": list(event.get("waypoints", [])),
            "values": values,
            **self._link(self.root),
            **self._passthrough(event),
        }, source_phase="refinement_done")
        self.active = None

    def winner(self, event):
        values = {"distance_m": _finite(event.get("distance_m"))}
        _flatten(event, "objective_before", values)
        _flatten(event, "objective_after", values)
        self._append({
            "kind": "select",
            "phase": "winner",
            "paths": [list(path) for path in event["paths"]],
            "nodes": list(event.get("waypoints", [])),
            "values": values,
            "decision": {"accepted": bool(event.get("accepted", True)),
                         "reason": f"{_WINNER_REASON} {_reason(event)}"},
            **self._link(self.root),
            **self._passthrough(event),
        }, source_phase="winner")
        self.active = None

    def shake(self, event):
        (level,) = _require(event, "shake_level")
        self.vns_index += 1
        self.active = f"{self.root}:vns:{self.vns_index}"
        self._append({
            "kind": "route_changed",
            "phase": "shake",
            "paths": [list(path) for path in event["paths"]],
            "nodes": list(event.get("waypoints", [])),
            # 교란 자체는 채택 판단이 아니다. 판단은 이어지는 vns_decision이 한다.
            "values": {"shake_level": level, "note": _SHAKE_NOTE,
                       "distance_m": _finite(event.get("distance_m"))},
            **self._link(self.active),
            **self._passthrough(event),
        }, source_phase="shake")

    def shake_failed(self, event):
        (level,) = _require(event, "shake_level")
        self.vns_index += 1
        self.active = f"{self.root}:vns:{self.vns_index}"
        self._append({
            "kind": "reject",
            "phase": "shake_failed",
            "paths": [],
            "values": {"shake_level": level},
            "decision": {"accepted": False, "reason": _SHAKE_FAILED_REASON},
            **self._link(self.active),
            **self._passthrough(event),
        }, source_phase="shake_failed")

    def vns_decision(self, event):
        accepted, level = _require(event, "accepted", "shake_level")
        values = {"shake_level": level, "distance_m": _finite(event.get("distance_m"))}
        _flatten(event, "objective_before", values)
        _flatten(event, "objective_after", values)
        self._append({
            "kind": "select" if accepted else "reject",
            "phase": "vns_decision",
            "paths": [list(path) for path in event["paths"]],
            "nodes": list(event.get("waypoints", [])),
            "values": values,
            "decision": {"accepted": bool(accepted), "reason": _reason(event)},
            **self._link(self.active or self.root),
            **self._passthrough(event),
        }, source_phase="vns_decision")

    def destroy(self, event):
        self.alns_index += 1
        self.active = f"{self.root}:alns:{self.alns_index}"
        self._operator(event, "destroy")

    def repair(self, event):
        if self.active is None:
            # repair는 항상 같은 ALNS 반복의 destroy 뒤에 온다.
            raise TraceMismatchError("destroy 없이 repair 기록이 먼저 나왔습니다.")
        self._operator(event, "repair")

    def alns_accept(self, event):
        (accepted,) = _require(event, "accepted")
        values = {"accepted": bool(accepted), "delta": _finite(event.get("delta")),
                  "temperature": _finite(event.get("temperature"))}
        _flatten(event, "internal_before", values)
        _flatten(event, "internal_after", values)
        # 내부 수락은 최종 채택이 아니므로 decision을 달지 않는다(select/reject 금지).
        self._append({
            "kind": "evaluate",
            "phase": "alns_accept",
            "paths": [],
            "nodes": list(event.get("waypoints", [])),
            "values": values,
            **self._link(self.active or self.root),
            **self._passthrough(event),
        }, source_phase="alns_accept")

    def alns_result(self, event):
        (accepted,) = _require(event, "accepted")
        values = {"distance_m": _finite(event.get("distance_m"))}
        _flatten(event, "objective_before", values)
        _flatten(event, "objective_after", values)
        self._append({
            "kind": "select" if accepted else "reject",
            "phase": "alns_result",
            "paths": [list(path) for path in event["paths"]],
            "nodes": list(event.get("waypoints", [])),
            "values": values,
            "decision": {"accepted": bool(accepted), "reason": _reason(event)},
            **self._link(self.root),
            **self._passthrough(event),
        }, source_phase="alns_result")
        self.active = None

    def prune(self, event):
        (before,) = _require(event, "before")
        after = list(event["paths"][0]) if event["paths"] else []
        removed = [node for node in before if node not in set(after)]
        self._append({
            "kind": "cleanup",
            "phase": "prune",
            "paths": [after],
            "values": {"removed_nodes": len(before) - len(after)},
            "focus": {"nodes": removed or ([after[0], after[-1]] if after else [])},
            "before": list(before),
        }, source_phase="prune")

    def final(self, paths):
        paths = [list(path) for path in paths]
        self._append({
            "kind": "final",
            "phase": "final",
            "paths": paths,
            "values": {"candidates": len(paths)},
            "decision": {"accepted": True, "reason": _FINAL_REASON},
            "focus": {"nodes": [self.start_node, self.end_node]},
        })

    # ── 내부 ───────────────────────────────────────────────────
    def _operator(self, event, stage):
        (operator,) = _require(event, "operator")
        self._append({
            "kind": "candidates",
            "phase": stage,
            "paths": [],
            "nodes": list(event.get("waypoints", [])),
            "values": {"operator": operator, "stage": stage},
            **self._link(self.active),
            **self._passthrough(event),
        }, source_phase=stage)

    def _finish_construction(self, call):
        """구축 호출 하나가 끝났다. 이후 정제 이벤트는 이 번호를 뿌리로 쓴다.

        VNS의 전체 재구축(`waypoint_refinement._shake` level 4 이상)도 같은 구축 함수를
        부르므로 이 번호가 올라간다. 그래서 `n`은 "외부 재시작"이 아니라 "구축 호출
        순번"이다.
        """
        if not isinstance(call, int):
            raise TraceMismatchError(
                f"construction_call이 정수가 아닙니다({call!r}). 재시작 번호를 만들 수 없습니다."
            )
        self.restart = call
        self.pending_call = None
        self.vns_index = self.alns_index = 0
        self.active = None


def record_waypoint_trace(trace, *, engine, mode, start_node, end_node, paths, target_m=None,
                          seed=None, code_commit=None, artifact=None, config=None):
    """GRASP·경유지 계열 원본 기록을 공통 이벤트와 실행 조건으로 바꾼다.

    Args:
        trace: `run()`이 끝난 `waypoint_trace.WaypointTrace`.
        engine: 기록을 만든 `WaypointEngine` 인스턴스.
        mode: 결과 구분 이름(`"grasp_vnd"` 등).
        start_node·end_node: 스냅한 출발·도착 노드. 순환이라 두 값이 같다.
        paths: 엔진이 실제로 반환한 경로 노드열 목록. `final` 이벤트가 된다.
        target_m·seed·code_commit·artifact·config: 실행 조건에 그대로 기록한다.

    Returns:
        `{"events", "conditions"}`. `events`는 `validate_events()`를 통과한 목록이다.

    Raises:
        TraceMismatchError: 모르는 phase, 필요한 키 없음처럼 변환할 수 없는 원본 기록을
            만났을 때. `accepted` 플래그가 있는 모르는 phase도 여기서 멈춘다.
    """
    builder = _WaypointEvents(engine=engine, start_node=start_node, end_node=end_node,
                              config=engine.config)
    handlers = {
        "grasp_choice": builder.grasp_choice, "constructed": builder.constructed,
        "construction_failed": builder.construction_failed, "neighbor": builder.neighbor,
        "improved": builder.improved, "refinement_done": builder.refinement_done,
        "winner": builder.winner, "shake": builder.shake, "shake_failed": builder.shake_failed,
        "vns_decision": builder.vns_decision, "destroy": builder.destroy,
        "repair": builder.repair, "alns_accept": builder.alns_accept,
        "alns_result": builder.alns_result, "prune": builder.prune,
    }
    for event in trace.events:
        phase = event.get("phase")
        handler = handlers.get(phase)
        if handler is None:
            raise TraceMismatchError(
                f"모르는 원본 phase입니다: {phase!r}. 변환 규칙에 없는 기록을 건너뛰지 않고 "
                f"중단합니다(사용 가능: {', '.join(sorted(handlers))})."
            )
        handler(event)
    builder.final(paths)
    conditions = RunConditions(
        algorithm=ALGORITHM,
        engine_class=type(engine).__name__,
        mode=mode,
        # 경유지 구간 연결도 Haversine A*다. ALT 거리표는 쓰지 않는다.
        heuristic=HeuristicConditions(name="haversine"),
        weight_policy=_weight_policy(engine.config),
        service_use=service_use_for(type(engine)),
        code_commit=code_commit,
        artifact=ArtifactRef(**artifact) if artifact else ArtifactRef(),
        target_m=target_m,
        seed=seed,
        config=dict(config or {}),
    )
    return {"events": validate_events(builder.events), "conditions": conditions}
