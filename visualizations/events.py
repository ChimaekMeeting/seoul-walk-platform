"""알고리즘 어댑터가 공통으로 내는 이벤트 형식과 실행 조건.

여러 알고리즘(A*·ALT, Beam, GRASP 계열)의 탐색 과정을 같은 화면에서 읽으려면 기록
구조가 하나여야 한다. 이 모듈이 그 단일 기준이다 — 어댑터는 여기 정의한 키만 쓰고,
내보내기 전에 반드시 `validate_events()`를 통과시킨다. 기록 구조가 맞지 않으면
잘못된 장면을 만들지 않고 `ValueError`로 중단한다.

## 이벤트 필수 키

| 키 | 형 | 뜻 |
|---|---|---|
| `seq` | int | 0부터 1씩 증가하는 단계 순서 |
| `kind` | str | 공통 어휘(`KINDS`) 중 하나 |
| `algorithm` | str | 어댑터가 정하는 알고리즘 식별자(예: `"astar"`) |
| `phase` | str | 기존 재생 화면이 읽는 세부 단계명(예: `"start"`, `"astar"`, `"final"`) |
| `paths` | list[list] | 이 장면과 관련된 경로 노드열 목록(없으면 `[]`) |

`phase`는 화면 호환용이다. 재생 화면은 당분간 `phase`로 설명 문구를 고르므로,
어댑터는 기존 화면이 아는 이름을 그대로 써야 한다.

## 이벤트 선택 키

| 키 | 형 | 뜻 |
|---|---|---|
| `candidate_id` | str | 같은 후보의 흐름을 잇는 식별자 |
| `parent_candidate_id` | str | 이 후보가 갈라져 나온 부모 후보 식별자 |
| `nodes` | list | 이 장면과 관련된 노드 목록 |
| `values` | dict | 판단에 쓴 수치. 화면이 그대로 표시할 수 있는 값만 담는다 |
| `decision` | dict | `{"accepted": bool, "reason": str}` — 실제 기록으로 확인되는 문장만 |
| `focus` | dict | `{"nodes": [...]}` 자동 확대에 쓸 관심 노드(PR-C에서 사용) |

그 밖의 기존 키(`current`, `frontier`, `popped`, `tree`, `explored`, `before` 등)는
화면 호환을 위해 그대로 허용한다 — 검사하지 않고 통과시킨다.

## values에 담을 수 있는 값

최상위는 숫자·문자열·리스트(또는 `None`)만 허용한다. 리스트 항목은 스칼라이거나 한
겹 dict(표 한 줄)까지 허용한다 — `frontier_top`·`h_terms`·`expanded`처럼 줄 단위로
표시하는 항목 때문이다. 집합·그래프·엔진 내부 자료구조 같은 객체는 거부한다.
`float("inf")`·`nan`도 거부한다(JSON으로 나가면 화면의 `JSON.parse`가 실패한다).
숫자로 표시할 수 없는 자리는 `None`으로 남긴다.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

# 공통 어휘. 어댑터는 여기 없는 kind를 쓰지 않는다.
KIND_MEANINGS = {
    "run_start": "실행 시작. 입력과 조건을 알린다.",
    "candidates": "이번 단계에서 만들어진 후보 목록.",
    "evaluate": "후보를 평가했다(채택 여부는 아직 아님).",
    "select": "후보를 골랐다.",
    "reject": "후보를 버렸다.",
    "route_changed": "현재 경로가 실제로 바뀌었다.",
    "cleanup": "기존 정리 규칙을 적용했다.",
    "final": "엔진이 반환한 결과.",
}
KINDS = tuple(KIND_MEANINGS)

REQUIRED_KEYS = ("seq", "kind", "algorithm", "phase", "paths")

_SCALARS = (bool, int, float, str)


@dataclass(frozen=True)
class ArtifactRef:
    """실행에 쓴 도보망 artifact의 식별 정보."""

    data_version: str | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class HeuristicConditions:
    """A* 계열이 쓴 휴리스틱의 준비 조건.

    Haversine이면 `name="haversine"`에 나머지는 전부 `None`이다.
    """

    name: str
    method: str | None = None
    k_requested: int | None = None
    k_actual: int | None = None
    seed: int | None = None
    # [{"node": int, "lat": float, "lon": float}, ...]
    landmarks: list[dict] | None = None
    select_s: float | None = None
    table_s: float | None = None


@dataclass(frozen=True)
class RunConditions:
    """한 실행 결과에 하나씩 붙는 실행 조건.

    화면과 문서가 "무엇을 어떤 조건으로 돌린 기록인가"를 이 값 하나로 읽는다.
    """

    algorithm: str
    engine_class: str
    mode: str
    heuristic: HeuristicConditions
    weight_policy: str
    code_commit: str | None = None
    artifact: ArtifactRef = field(default_factory=ArtifactRef)
    target_m: float | None = None
    seed: int | None = None
    config: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        """JSON으로 저장할 수 있는 dict. 결과 파일과 화면 payload가 함께 쓴다."""
        return asdict(self)


def _fail(where: str, message: str) -> None:
    raise ValueError(f"{where}: {message}")


def _check_scalar(value, where: str) -> None:
    if value is None:
        return
    if not isinstance(value, _SCALARS):
        _fail(where, f"숫자·문자열만 담을 수 있습니다(받은 형: {type(value).__name__}).")
    if isinstance(value, float) and not math.isfinite(value):
        _fail(where, f"유한하지 않은 수({value})는 화면에 표시할 수 없습니다. None으로 남기세요.")


def _check_values(values, where: str) -> None:
    if not isinstance(values, dict):
        _fail(where, f"values는 dict여야 합니다(받은 형: {type(values).__name__}).")
    for key, value in values.items():
        if not isinstance(key, str):
            _fail(where, f"values의 키는 문자열이어야 합니다({key!r}).")
        spot = f"{where}.values[{key!r}]"
        if isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    for sub_key, sub_value in item.items():
                        if not isinstance(sub_key, str):
                            _fail(f"{spot}[{i}]", f"키는 문자열이어야 합니다({sub_key!r}).")
                        _check_scalar(sub_value, f"{spot}[{i}][{sub_key!r}]")
                else:
                    _check_scalar(item, f"{spot}[{i}]")
        elif isinstance(value, dict):
            _fail(spot, "values 최상위에는 dict를 담지 않습니다. 숫자·문자열·리스트만 쓰세요.")
        else:
            _check_scalar(value, spot)


def _check_decision(decision, where: str) -> None:
    if not isinstance(decision, dict):
        _fail(where, f"decision은 dict여야 합니다(받은 형: {type(decision).__name__}).")
    missing = sorted({"accepted", "reason"} - set(decision))
    if missing:
        _fail(where, f"decision에 {', '.join(missing)}가 없습니다.")
    if not isinstance(decision["accepted"], bool):
        _fail(where, "decision['accepted']는 bool이어야 합니다.")
    if not isinstance(decision["reason"], str) or not decision["reason"].strip():
        _fail(where, "decision['reason']에는 실제 기록으로 확인되는 문장을 씁니다.")


def _check_focus(focus, where: str) -> None:
    if not isinstance(focus, dict):
        _fail(where, f"focus는 dict여야 합니다(받은 형: {type(focus).__name__}).")
    if not isinstance(focus.get("nodes"), list):
        _fail(where, "focus에는 리스트 nodes가 있어야 합니다.")


def validate_events(events) -> list:
    """어댑터가 만든 이벤트 목록을 공통 형식으로 검사한다.

    검사 항목: seq 연속성(0부터 1씩), kind 어휘, 필수 키, paths 구조, values 타입,
    decision·focus 구조, 그리고 기록이 `run_start`로 시작해 `final`로 끝나는지.

    Raises:
        ValueError: 위 조건 중 하나라도 어긋났을 때. 어떤 이벤트의 어떤 키가
            문제인지 메시지에 남긴다.
    """
    if not isinstance(events, list) or not events:
        raise ValueError("이벤트 기록이 비어 있습니다. 재생할 장면이 없으면 결과를 만들지 않습니다.")
    for i, event in enumerate(events):
        where = f"{i}번째 이벤트"
        if not isinstance(event, dict):
            _fail(where, f"이벤트는 dict여야 합니다(받은 형: {type(event).__name__}).")
        missing = [key for key in REQUIRED_KEYS if key not in event]
        if missing:
            _fail(where, f"필수 키가 없습니다: {', '.join(missing)}")
        if event["seq"] != i:
            _fail(where, f"seq는 0부터 1씩 증가해야 합니다(받은 값: {event['seq']!r}).")
        if event["kind"] not in KINDS:
            _fail(where, f"모르는 kind입니다: {event['kind']!r}. 사용 가능: {', '.join(KINDS)}")
        for key in ("algorithm", "phase"):
            if not isinstance(event[key], str) or not event[key]:
                _fail(where, f"{key}는 비어 있지 않은 문자열이어야 합니다.")
        if not isinstance(event["paths"], list):
            _fail(where, f"paths는 리스트여야 합니다(받은 형: {type(event['paths']).__name__}).")
        for j, path in enumerate(event["paths"]):
            if not isinstance(path, list):
                _fail(where, f"paths[{j}]는 노드 리스트여야 합니다.")
        for key in ("candidate_id", "parent_candidate_id"):
            if key in event and not isinstance(event[key], str):
                _fail(where, f"{key}는 문자열이어야 합니다.")
        if "nodes" in event and not isinstance(event["nodes"], list):
            _fail(where, "nodes는 리스트여야 합니다.")
        if "values" in event:
            _check_values(event["values"], where)
        if "decision" in event:
            _check_decision(event["decision"], where)
        if "focus" in event:
            _check_focus(event["focus"], where)
    if events[0]["kind"] != "run_start":
        _fail("0번째 이벤트", f"기록은 run_start로 시작해야 합니다(받은 kind: {events[0]['kind']!r}).")
    if events[-1]["kind"] != "final":
        _fail(f"{len(events) - 1}번째 이벤트",
              f"기록은 final로 끝나야 합니다(받은 kind: {events[-1]['kind']!r}).")
    return events
