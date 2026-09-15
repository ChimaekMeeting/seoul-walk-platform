"""실제 A*(OnewayAstarEngine) 실행을 재생해 공통 이벤트로 만드는 어댑터.

## 왜 "재생"인가

기존 `route_trace.SearchTrace`는 `sys.settrace`로 NetworkX 내부 프레임의 지역 변수를
훔쳐봤다. 디버거·커버리지와 같이 못 쓰고, 라이브러리 줄 번호에 묶이며, 모든 줄마다
파이썬 콜백이 걸려 느리다. 그래서 A*는 다른 방법을 쓴다.

1. **실제 실행**: 서비스와 똑같이 `OnewayAstarEngine.run()`을 계측 없이 한 번 돌린다.
   반환 경로는 `engine.last_path_nodes`다.
2. **재생**: 같은 그래프·같은 휴리스틱·같은 비용 함수로 계측판 A*
   (`benchmarks.runner._astar_instrumented.astar_path_instrumented`)를 다시 돌려 단계별
   이벤트를 만든다.
3. **일치 확인**: 재생 경로가 엔진 반환 경로와 **노드열까지** 같은지 확인하고, 다르면
   `TraceMismatchError`로 중단한다. 잘못된 장면을 만들지 않는다.

재생이 실제 탐색과 같다고 말할 수 있는 근거는 계측판이 `nx.astar_path`의 복제이기
때문이다 — 우선순위 튜플에 단조 증가 카운터를 넣는 동점 처리까지 원본과 같아서, 같은
입력에서 꺼내는 순서가 결정적으로 같다. 이 대조는 PR #420에서 추가한
`tests/unit/test_alt_shortest_path_runner.py`가 지킨다. 다만 계측판이 원본의 복제인
이상 NetworkX를 올릴 때는 두 파일을 다시 대조해야 한다.

## 엔진 내부에 기대는 것

재생하려면 엔진이 실제로 쓴 휴리스틱과 비용 함수를 알아야 한다. `_active_heuristic`은
private 이름이라 `getattr`로 읽고, 없으면 "엔진 계약이 바뀌었습니다"라고 즉시
`RuntimeError`를 낸다 — 조용히 다른 조건으로 재생하지 않기 위해서다.

화면(`route_player.html`)은 엔진의 변수명이나 줄 번호를 직접 참조하지 않는다. 화면이
읽는 것은 이 어댑터가 만든 공통 이벤트(`visualizations/events.py`)뿐이다.
"""

from __future__ import annotations

import math
from heapq import nsmallest

import networkx as nx

from benchmarks.runner._astar_instrumented import astar_path_instrumented
from src.route_engine.alt_runtime import get_alt_info
from src.route_engine.engines.path_utils import _RETURN_REVISIT_PENALTY
from src.route_engine.scoring.scoring_engine import compute_distance_only_lookup
from visualizations.events import (
    ArtifactRef,
    HeuristicConditions,
    RunConditions,
    TraceMismatchError,
    service_use_for,
    validate_events,
)

__all__ = ["ALGORITHM", "TraceMismatchError", "record_astar_run"]

ALGORITHM = "astar"
# 한 장면에 텍스트로 보여 줄 대기 후보 수. 전체 대기 목록은 frontier 키에 그대로 있다.
FRONTIER_TOP = 5
# h = max_L |d(L,u) - d(L,v)| 를 항별로 다시 더했을 때 허용하는 오차(m).
BOUND_TOLERANCE_M = 1e-6

_SELECT_REASON = "대기 후보 중 f = g + h 가 가장 작아 큐에서 꺼냈습니다."
_STALE_REASON = (
    "대기 후보 중 f = g + h 가 가장 작아 꺼냈지만, 이미 더 나은 경로로 확장한 "
    "노드라 이번 항목은 건너뜁니다."
)
_FINAL_REASON = "엔진이 반환한 경로입니다. 재생 경로가 노드열까지 같은지 확인했습니다."

_MISSING = object()

# 재생 결과가 실제 엔진 반환과 다를 때 쓰는 예외는 events.py가 어댑터 공통으로 가진다.


def _finite(value):
    """차단 엣지(inf)처럼 숫자로 표시할 수 없는 값은 None으로 남긴다."""
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


class _AstarRecorder:
    """계측 A*의 관찰자. pop 한 번이 장면 하나가 된다.

    `explored`와 `queue`는 읽기만 한다(계측판의 계약). 이웃 하나하나를 따로 장면으로
    만들지 않고, 그 pop에서 확장·건너뛴 이웃을 같은 장면의
    `values["expanded"]`에 모아 넣는다. 그래서 이벤트 수는 `pop 수 + 2`
    (`run_start` 1개 + pop마다 1개 + `final` 1개)다.
    """

    def __init__(self, *, heuristic, heuristic_name, start, end, landmark_table):
        self.heuristic = heuristic
        self.start = start
        self.end = end
        self.table = landmark_table
        self.h_kind = "alt" if landmark_table else "haversine"
        self.pops = 0
        self.current = None
        self.events = [{
            "seq": 0,
            "kind": "run_start",
            "algorithm": ALGORITHM,
            "phase": "start",
            "paths": [[start]],
            "nodes": [start, end],
            "values": {"start": start, "end": end, "heuristic": heuristic_name},
            "focus": {"nodes": [start, end]},
        }]

    # ── 관찰자 훅 ──────────────────────────────────────────────
    def on_pop(self, node, g, parent, explored, queue):
        self.pops += 1
        h = float(self.heuristic(node, self.end))
        top = [
            {"node": item[2], "f_m": _finite(item[0]), "g_m": _finite(item[3]),
             "h_m": _finite(item[0] - item[3])}
            for item in nsmallest(FRONTIER_TOP, queue)
        ]
        values = {
            "g_m": _finite(g),
            "h_m": _finite(h),
            "f_m": _finite(g + h),
            "h_kind": self.h_kind,
            "frontier_top": top,
            "expanded": [],
        }
        terms = self._landmark_terms(node, h)
        if terms is not None:
            best = max(terms, key=lambda term: term["bound_m"], default=None)
            values["h_terms"] = terms
            values["best_landmark"] = best["landmark"] if best else None
        event = {
            "seq": len(self.events),
            "kind": "select",
            "algorithm": ALGORITHM,
            "phase": "astar",  # 기존 재생 화면이 A* 장면을 고르는 이름
            "paths": [self._chain(node, parent, explored)],
            "nodes": [node],
            "values": values,
            "decision": {"accepted": True, "reason": _SELECT_REASON},
            "focus": {"nodes": [node, *(item["node"] for item in top)]},
            # 아래는 기존 화면이 그대로 읽는 키다(화면 호환).
            "current": node,
            "popped": self.pops,
            "tree": [[p, child] for child, p in explored.items() if p is not None],
            "explored": list(explored),
            "frontier": sorted({item[2] for item in queue}),
            "distance_m": _finite(g),
        }
        self.events.append(event)
        self.current = event

    def on_push(self, node, g, h, f, parent, reason):
        self._expanded().append({
            "node": node,
            "g_m": _finite(g),
            "h_m": _finite(h),
            "f_m": _finite(f),
            "result": "pushed_new" if reason == "new" else "pushed_improved",
            "reason": reason,
        })

    def on_skip(self, node, reason):
        if reason == "stale":
            # 이웃이 아니라 방금 꺼낸 항목 자체를 버린 경우다.
            event = self._require_current()
            event["decision"] = {"accepted": False, "reason": _STALE_REASON}
            event["values"]["stale"] = True
            return
        self._expanded().append({
            "node": node,
            "g_m": None,
            "h_m": None,
            "f_m": None,
            "result": "skipped",
            "reason": reason,
        })

    # ── 내부 ───────────────────────────────────────────────────
    def _require_current(self):
        if self.current is None:
            raise TraceMismatchError(
                "큐에서 꺼내기 전에 확장 기록이 들어왔습니다. 계측 A*의 훅 순서를 확인하세요."
            )
        return self.current

    def _expanded(self):
        return self._require_current()["values"]["expanded"]

    def _chain(self, node, parent, explored):
        chain = [node]
        ancestor = parent
        while ancestor is not None:
            chain.append(ancestor)
            ancestor = explored[ancestor]
        chain.reverse()
        return chain

    def _landmark_terms(self, node, h):
        """ALT일 때 h를 랜드마크별 하한 항으로 분해한다. Haversine이면 None.

        랜드마크 좌표는 실행 조건에만 넣고 이벤트에는 노드 번호만 남긴다 — 외곽
        랜드마크가 화면 범위 계산(`route_view.event_nodes`)에 들어가면 지도가 터진다.
        """
        if not self.table:
            return None
        terms = []
        for landmark, row in self.table.items():
            d_node, d_end = row.get(node), row.get(self.end)
            if d_node is None or d_end is None:
                continue
            terms.append({
                "landmark": int(landmark),
                "d_L_node_m": float(d_node),
                "d_L_end_m": float(d_end),
                "bound_m": abs(float(d_node) - float(d_end)),
            })
        best = max((term["bound_m"] for term in terms), default=0.0)
        if abs(best - h) > BOUND_TOLERANCE_M:
            raise TraceMismatchError(
                f"랜드마크 항을 다시 더한 하한({best})이 실제 휴리스틱 값({h})과 다릅니다. "
                "거리표와 휴리스틱이 같은 실행의 것인지 확인하세요."
            )
        return terms

    def finish(self, path, distance_m, popped, pushed):
        self.events.append({
            "seq": len(self.events),
            "kind": "final",
            "algorithm": ALGORITHM,
            "phase": "final",
            "paths": [list(path)],
            "nodes": list(path),
            "values": {"distance_m": _finite(distance_m), "popped": popped, "pushed": pushed},
            "decision": {"accepted": True, "reason": _FINAL_REASON},
            "focus": {"nodes": [self.start, self.end]},
        })


def _engine_contract(engine):
    """재생에 필요한 엔진 속성을 한 번에 읽는다. 하나라도 없으면 계약 변경이다."""
    contract = {
        "heuristic": getattr(engine, "_active_heuristic", _MISSING),
        "heuristic_name": getattr(engine, "heuristic_name", _MISSING),
        "blocked_tags": getattr(engine, "blocked_tags", _MISSING),
        "visited_nodes": getattr(engine, "visited_nodes", _MISSING),
    }
    missing = sorted(name for name, value in contract.items() if value is _MISSING)
    if missing:
        raise RuntimeError(
            f"엔진 계약이 바뀌었습니다: {type(engine).__name__}에서 "
            f"{', '.join(missing)}을(를) 읽지 못했습니다. "
            "visualizations/astar_adapter.py의 재생 조건을 다시 맞추세요."
        )
    if not callable(contract["heuristic"]):
        raise RuntimeError(
            "엔진 계약이 바뀌었습니다: _active_heuristic이 호출 가능한 휴리스틱이 아닙니다."
        )
    return contract


def _heuristic_conditions(graph, name, table, alt_seed):
    """실행 조건에 넣을 휴리스틱 내역. 랜드마크 좌표는 여기에만 들어간다."""
    info = get_alt_info(graph)
    if table is None or info is None:
        return HeuristicConditions(name=name)
    return HeuristicConditions(
        name=name,
        method=info.get("method"),
        k_requested=info.get("k_requested"),
        k_actual=info.get("k_actual"),
        seed=alt_seed,
        landmarks=[{"node": int(n),
                    "lat": float(graph.nodes[n]["lat"]),
                    "lon": float(graph.nodes[n]["lon"])}
                   for n in info.get("landmarks", [])],
        select_s=info.get("select_s"),
        table_s=info.get("table_s"),
    )


def _weight_policy(blocked_tags, visited_nodes):
    visited = f"{len(visited_nodes)}개" if visited_nodes else "없음"
    return (
        "기본 엣지 비용 = length(compute_distance_only_lookup). "
        f"blocked_tags({len(blocked_tags)}개) 엣지는 inf. "
        f"기방문 노드는 도착지를 빼고 {_RETURN_REVISIT_PENALTY}배 — "
        f"이번 실행의 visited_nodes는 {visited}."
    )


def record_astar_run(engine, graph, *, mode, target_m=None, seed=None, alt_seed=None,
                     code_commit=None, artifact=None, config=None):
    """엔진을 실제로 실행하고 그 실행을 재생해 공통 이벤트를 만든다.

    Args:
        engine: 아직 `run()`을 호출하지 않은 `OnewayAstarEngine`.
        graph: 엔진이 쓰는 그래프(=`engine.G`). 시각화가 만든 깊은 복사본이다.
        mode: 결과를 구분할 이름(`"shortest"`, `"shortest_alt"`).
        target_m·seed·alt_seed·code_commit·artifact·config: 실행 조건에 그대로 기록한다.

    Returns:
        `{"events", "conditions", "popped", "pushed", "responses", "paths"}`.
        `events`는 `validate_events()`를 통과한 목록, `conditions`는 `RunConditions`,
        `responses`는 엔진이 돌려준 원래 응답 객체다.

    Raises:
        RuntimeError: 엔진 계약이 바뀌어 재생 조건을 읽지 못할 때.
        TraceMismatchError: 재생 경로가 엔진 반환 경로와 다를 때, 또는 재생할 실행
            기록 자체가 없을 때.
    """
    if graph is not engine.G:
        raise ValueError("재생에는 엔진이 실제로 쓴 그래프를 그대로 넘겨야 합니다.")
    contract = _engine_contract(engine)
    heuristic = contract["heuristic"]

    # (b) 원본 호출은 그대로 두고 인자만 캡처한다. settrace를 쓰지 않는다.
    captured = {}
    original_find_path = engine.find_path

    def capture_find_path(start, end):
        captured["start"], captured["end"] = start, end
        return original_find_path(start, end)

    engine.find_path = capture_find_path
    try:
        responses = engine.run()  # (c) 계측 없이 서비스와 똑같이 실행
    finally:
        del engine.find_path  # 인스턴스 속성만 지워 클래스 메서드로 되돌린다

    if "start" not in captured:
        raise TraceMismatchError(
            "엔진이 find_path를 호출하지 않았습니다(출발·도착 노드 연결 실패). "
            "재생할 탐색 기록이 없습니다."
        )
    path_nodes = list(getattr(engine, "last_path_nodes", None) or [])
    if not path_nodes:
        raise TraceMismatchError("엔진이 경로를 반환하지 않아 재생할 기록이 없습니다.")

    start, end = captured["start"], captured["end"]
    visited_nodes = contract["visited_nodes"]
    base_weight = compute_distance_only_lookup(graph, contract["blocked_tags"])["weight"]

    def weight(u, v, data):
        # find_path의 _weight와 같은 규칙: 도착지 자신은 재방문 페널티에서 뺀다.
        base = base_weight(u, v, data)
        if v in visited_nodes and v != end:
            return base * _RETURN_REVISIT_PENALTY
        return base

    table = getattr(heuristic, "landmark_table", None)
    recorder = _AstarRecorder(heuristic=heuristic, heuristic_name=contract["heuristic_name"],
                              start=start, end=end, landmark_table=table)
    try:
        replayed, popped, pushed = astar_path_instrumented(
            graph, start, end, heuristic=heuristic, weight=weight, observer=recorder
        )
    except nx.NetworkXNoPath as exc:
        raise TraceMismatchError(
            "엔진은 경로를 찾았는데 같은 조건의 재생에서는 경로가 없습니다. "
            "재생 조건(휴리스틱·비용 함수)을 다시 확인하세요."
        ) from exc
    if replayed != path_nodes:  # (f) 노드열까지 같아야 한다
        raise TraceMismatchError(
            f"재생한 A* 경로가 엔진 반환 경로와 다릅니다(재생 {len(replayed)}개 노드, "
            f"엔진 {len(path_nodes)}개 노드). 잘못된 장면을 만들지 않고 중단합니다."
        )

    recorder.finish(path_nodes, engine.utils.calc_distance(path_nodes), popped, pushed)
    conditions = RunConditions(
        algorithm=ALGORITHM,
        engine_class=type(engine).__name__,
        mode=mode,
        heuristic=_heuristic_conditions(graph, contract["heuristic_name"], table, alt_seed),
        weight_policy=_weight_policy(contract["blocked_tags"], visited_nodes),
        # OnewayAstarEngine은 RouteService.base_engines에 있는 서비스 엔진이다.
        service_use=service_use_for(type(engine)),
        code_commit=code_commit,
        artifact=ArtifactRef(**artifact) if artifact else ArtifactRef(),
        target_m=target_m,
        seed=seed,
        config=dict(config or {}),
    )
    return {
        "events": validate_events(recorder.events),
        "conditions": conditions,
        "popped": popped,
        "pushed": pushed,
        "responses": responses,
        "paths": [path_nodes],
    }
