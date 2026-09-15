"""Beam 계열(순환·편도) 탐색 기록을 공통 이벤트로 바꾸는 어댑터.

입력은 현재 settrace 수집물(`route_trace.SearchTrace`, 오프라인 전용)이며, 엔진 훅이
승인되면 입력만 바뀐다 — 이 어댑터와 `events.py`는 그대로 남는다. 훅 제안은
`docs/proposals/route_engine_trace_observer_proposal.md`에 있다.

## 하는 일

원본 기록은 Beam 엔진이 실제로 한 일을 phase 이름으로 남긴다(`expand`·`keep`·
`connect`·`selection`·`prune`). 이 어댑터는 그 기록을 읽어 공통 어휘(`kind`)로 옮기고,
화면이 이미 읽는 원본 키(`iteration`·`generated`·`kept`·`finished`·`before`)는 그대로
둔 채 공통 키(`seq`·`kind`·`candidate_id`·`values`·`decision`·`focus`)를 덧붙인다.
그래서 파이프라인의 나머지(`route_story`·`route_view`·재생 화면)는 settrace 산출물을
직접 보지 않고 이 어댑터가 낸 공통 이벤트만 본다.

| 원본 phase | kind | 비고 |
|---|---|---|
| (없음) | `run_start` | 어댑터가 만든다. 입력 노드·목표 거리·beam 폭 |
| `expand` | `candidates` | 이번 반복에서 만들어진 확장 후보 전부 |
| `keep` | `select` | 상위 `kept`개로 남은 후보 |
| `keep`(차집합) | `reject` | 같은 반복의 `expand` − `keep`. 있을 때만 |
| `connect` | `route_changed` | 도착 연결(편도) 또는 출발지 복귀(순환) |
| `selection` | `select` | 엔진 `find_path`가 반환한 후보 |
| `prune` | `cleanup` | 기존 정리 규칙 전후 |
| (없음) | `final` | 엔진이 반환한 경로 전부 |

## 판단 이유를 짓지 않는다

원본 기록에는 후보별 평가값 수치가 없다. 상위 k개 절단만 기록되므로 `decision.reason`
에는 순위 사실("평가값 상위 N개 안/밖")만 적고 점수를 지어내지 않는다.

## candidate_id

후보는 노드열이다. `beam:{반복 번호}:{노드열 sha1 앞 10자}`로 만든다. 같은 노드열이
다른 반복에 다시 나타나면 반복 번호가 달라 id도 달라진다 — 의도한 것이다. Beam은 매
반복마다 후보 집합을 새로 자르므로 "언제의 후보인가"가 후보의 정체에 포함된다.

`parent_candidate_id`는 직전 반복의 유지 후보 중 이 후보의 접두사인 가장 긴 노드열의
id다. Beam 확장이 실제로 "유지 후보 + 이웃 한 칸"이라 접두사 관계가 부모 관계와 같다.
첫 반복의 후보는 부모가 없다(`None`) — 시작 노드 하나짜리 초기 빔은 기록에 없다.
"""

from __future__ import annotations

import hashlib
import sys

from src.route_engine.engines.path_utils import _RETURN_REVISIT_PENALTY
from visualizations.events import (
    ArtifactRef,
    HeuristicConditions,
    RunConditions,
    TraceMismatchError,
    service_use_for,
    validate_events,
)

ALGORITHM = "beam"
# 원본 기록이 낼 수 있는 phase. 여기 없는 이름이 오면 변환하지 않고 중단한다.
SOURCE_PHASES = ("expand", "keep", "connect", "selection", "prune")
# reject 이벤트가 쓰는 화면 단계명. 원본에는 없고 어댑터가 만든다.
DROP_PHASE = "drop"

_FINAL_REASON = "엔진 run()이 반환한 경로입니다."
_SELECTION_REASON = "엔진 find_path가 반환한 후보입니다."


def _candidate_id(iteration, nodes):
    """후보(노드열) 하나의 결정적 식별자."""
    digest = hashlib.sha1(",".join(map(str, nodes)).encode()).hexdigest()[:10]
    return f"beam:{iteration}:{digest}"


def _parent_id(previous, nodes):
    """직전 반복의 유지 후보 중 이 후보의 접두사인 가장 긴 노드열의 id."""
    best = None
    for prev_nodes, prev_id in previous:
        size = len(prev_nodes)
        if size < len(nodes) and tuple(nodes[:size]) == prev_nodes:
            if best is None or size > best[0]:
                best = (size, prev_id)
    return best[1] if best else None


def _ends(paths):
    """후보들의 끝 노드. candidates·select·reject 장면의 focus로 쓴다."""
    return [path[-1] for path in paths if path]


def _require(event, *keys):
    missing = [key for key in keys if key not in event]
    if missing:
        raise TraceMismatchError(
            f"원본 {event.get('phase')!r} 이벤트에 {', '.join(missing)} 키가 없습니다. "
            "변환할 수 없는 기록은 건너뛰지 않고 중단합니다."
        )
    return [event[key] for key in keys]


def _beam_width(engine):
    """엔진이 실제로 쓰는 빔 폭. 읽을 수 없으면 None으로 남긴다(추정하지 않는다)."""
    width = getattr(engine, "beam_width", None)
    if width is not None:
        return int(width)
    module = sys.modules.get(type(engine).__module__)
    width = getattr(module, "_BEAM_WIDTH", None)
    return int(width) if width is not None else None


def _weight_policy(mode):
    return (
        "기본 엣지 비용 = custom_score(시각화 실행에서 length로 대체, 후보 다양화 벡터도 거리). "
        f"도착·복귀 연결은 PathUtils.connect_to의 Haversine A*이며 기방문 노드는 {_RETURN_REVISIT_PENALTY}배. "
        f"기존 정리 규칙(prune_dead_ends)과 상위 k개 절단을 그대로 유지한다(mode={mode})."
    )


class _BeamEvents:
    """원본 기록을 순서대로 읽어 공통 이벤트를 쌓는다."""

    def __init__(self, *, engine, mode, start_node, end_node, target_m):
        self.mode = mode
        self.start_node = start_node
        self.end_node = end_node
        self.events = []
        # 직전 반복의 유지 후보: [(노드열 tuple, candidate_id), ...]
        self.previous_keep = []
        # 지금까지 유지된 모든 후보를 길이별로 모아 둔다. connect가 이어붙인 구간을
        # 찾을 때 긴 쪽부터 한 번에 조회하려는 것이다(전체 훑기 방지).
        self.kept_by_length = {}
        self.pending_expand = None
        self.pending_ids = {}
        self._append({
            "kind": "run_start",
            "phase": "start",
            "paths": [[start_node]],
            "nodes": [start_node, end_node],
            "values": {"start": start_node, "end": end_node, "target_m": target_m,
                       "beam_width": _beam_width(engine)},
            "focus": {"nodes": [start_node, end_node]},
        })

    def _append(self, event, source_phase=None):
        event = {"seq": len(self.events), "algorithm": ALGORITHM, **event}
        if source_phase is not None:
            event["source_phase"] = source_phase
        self.events.append(event)

    # ── 원본 phase별 변환 ──────────────────────────────────────
    def expand(self, event):
        iteration, generated, kept, finished = _require(
            event, "iteration", "generated", "kept", "finished")
        paths = [list(path) for path in event["paths"]]
        self.pending_ids = {}
        ids, parents = [], []
        for nodes in paths:
            identifier = _candidate_id(iteration, nodes)
            self.pending_ids[tuple(nodes)] = identifier
            ids.append(identifier)
            parents.append(_parent_id(self.previous_keep, nodes))
        self.pending_expand = (iteration, paths)
        self._append({
            "kind": "candidates",
            "phase": "expand",
            "paths": paths,
            "values": {"iteration": iteration, "generated": generated, "kept": kept,
                       "finished": finished, "candidate_ids": ids,
                       "parent_candidate_ids": parents},
            "focus": {"nodes": _ends(paths)},
            # 아래는 기존 화면이 그대로 읽는 원본 키다.
            "iteration": iteration, "generated": generated, "kept": kept, "finished": finished,
        }, source_phase="expand")

    def keep(self, event):
        iteration, generated, kept, finished = _require(
            event, "iteration", "generated", "kept", "finished")
        if self.pending_expand is None or self.pending_expand[0] != iteration:
            raise TraceMismatchError(
                f"{iteration}번째 반복의 keep 기록에 짝이 되는 expand 기록이 없습니다. "
                "원본 기록 순서를 확인하세요."
            )
        paths = [list(path) for path in event["paths"]]
        original = {"iteration": iteration, "generated": generated, "kept": kept,
                    "finished": finished}
        ids = [self._known_id(iteration, nodes) for nodes in paths]
        parents = [_parent_id(self.previous_keep, nodes) for nodes in paths]
        self._append({
            "kind": "select",
            "phase": "keep",
            "paths": paths,
            "values": {**original, "candidate_ids": ids, "parent_candidate_ids": parents},
            "decision": {"accepted": True, "reason": f"평가값 상위 {kept}개 안에 들어 유지"},
            "focus": {"nodes": _ends(paths)},
            **original,
        }, source_phase="keep")
        survivors = {tuple(nodes) for nodes in paths}
        dropped = [nodes for nodes in self.pending_expand[1] if tuple(nodes) not in survivors]
        if dropped:
            self._append({
                "kind": "reject",
                "phase": DROP_PHASE,
                "paths": dropped,
                "values": {**original, "dropped": len(dropped),
                           "candidate_ids": [self._known_id(iteration, nodes) for nodes in dropped],
                           "parent_candidate_ids": [_parent_id(self.previous_keep, nodes)
                                                    for nodes in dropped]},
                "decision": {"accepted": False, "reason": f"평가값 상위 {kept}개 밖"},
                "focus": {"nodes": _ends(dropped)},
                **original,
            }, source_phase="keep")
        self.previous_keep = [(tuple(nodes), identifier) for nodes, identifier in zip(paths, ids)]
        for nodes, _ in self.previous_keep:
            self.kept_by_length.setdefault(len(nodes), set()).add(nodes)
        self.pending_expand = None

    def connect(self, event):
        path = list(event["paths"][0]) if event["paths"] else []
        if not path:
            raise TraceMismatchError("connect 기록에 연결된 경로가 없습니다.")
        connection = "출발지 복귀" if self.mode == "circular" else "도착 연결"
        self._append({
            "kind": "route_changed",
            "phase": "connect",
            "paths": [path],
            "values": {"connection": connection, "nodes_total": len(path)},
            "focus": {"nodes": self._connected_segment(path)},
        }, source_phase="connect")

    def selection(self, event):
        paths = [list(path) for path in event["paths"]]
        self._append({
            "kind": "select",
            "phase": "selection",
            "paths": paths,
            "values": {"candidates": len(paths)},
            "decision": {"accepted": True, "reason": _SELECTION_REASON},
            "focus": {"nodes": _ends(paths)},
        }, source_phase="selection")

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
            "nodes": list(paths[0]) if paths else [],
            "values": {"candidates": len(paths)},
            "decision": {"accepted": True, "reason": _FINAL_REASON},
            "focus": {"nodes": [self.start_node, self.end_node]},
        })

    # ── 내부 ───────────────────────────────────────────────────
    def _known_id(self, iteration, nodes):
        """expand에서 이미 부여한 id를 그대로 쓴다. 없으면 기록이 어긋난 것이다."""
        identifier = self.pending_ids.get(tuple(nodes))
        if identifier is None:
            raise TraceMismatchError(
                f"{iteration}번째 반복의 유지 후보가 같은 반복의 확장 후보에 없습니다. "
                "원본 기록이 실제 탐색과 어긋납니다."
            )
        return identifier

    def _connected_segment(self, path):
        """연결로 실제로 덧붙은 구간. 기록된 유지 후보 중 가장 긴 접두사 이후다.

        `connect_to`는 후보 노드열 뒤에 연결 경로를 이어 붙이므로, 기록에 남은 유지
        후보가 그 앞부분이다. 접두사를 못 찾으면(초기 빔에서 바로 연결한 경우) 경로
        전체를 관심 구간으로 남긴다 — 없는 구간을 지어내지 않는다.
        """
        for size in sorted((n for n in self.kept_by_length if n <= len(path)), reverse=True):
            if tuple(path[:size]) in self.kept_by_length[size]:
                return path[size - 1:]
        return list(path)


def record_beam_trace(trace, *, engine, mode, start_node, end_node, paths, target_m=None,
                      seed=None, code_commit=None, artifact=None, config=None):
    """Beam 계열 원본 기록을 공통 이벤트와 실행 조건으로 바꾼다.

    Args:
        trace: `run()`이 끝난 `route_trace.SearchTrace`.
        engine: 기록을 만든 엔진 인스턴스(`CircularBeamEngine`·`OnewayBeamEngine`).
        mode: 결과 구분 이름(`"circular"`, `"detour"`).
        start_node·end_node: 스냅한 출발·도착 노드. 순환이면 두 값이 같다.
        paths: 엔진이 실제로 반환한 경로 노드열 목록. `final` 이벤트가 된다.
        target_m·seed·code_commit·artifact·config: 실행 조건에 그대로 기록한다.

    Returns:
        `{"events", "conditions"}`. `events`는 `validate_events()`를 통과한 목록이다.

    Raises:
        TraceMismatchError: 모르는 phase, 필요한 키 없음, expand·keep 짝 불일치처럼
            변환할 수 없는 원본 기록을 만났을 때.
    """
    builder = _BeamEvents(engine=engine, mode=mode, start_node=start_node,
                          end_node=end_node, target_m=target_m)
    handlers = {"expand": builder.expand, "keep": builder.keep, "connect": builder.connect,
                "selection": builder.selection, "prune": builder.prune}
    for event in trace.events:
        phase = event.get("phase")
        handler = handlers.get(phase)
        if handler is None:
            raise TraceMismatchError(
                f"모르는 원본 phase입니다: {phase!r}. 변환 규칙에 없는 기록을 건너뛰지 않고 "
                f"중단합니다(사용 가능: {', '.join(SOURCE_PHASES)})."
            )
        handler(event)
    builder.final(paths)
    conditions = RunConditions(
        algorithm=ALGORITHM,
        engine_class=type(engine).__name__,
        mode=mode,
        # Beam 내부의 구간 연결은 PathUtils.astar_path가 쓰는 Haversine이다. ALT가 아니다.
        heuristic=HeuristicConditions(name="haversine"),
        weight_policy=_weight_policy(mode),
        service_use=service_use_for(type(engine)),
        code_commit=code_commit,
        artifact=ArtifactRef(**artifact) if artifact else ArtifactRef(),
        target_m=target_m,
        seed=seed,
        config=dict(config or {}),
    )
    return {"events": validate_events(builder.events), "conditions": conditions}
