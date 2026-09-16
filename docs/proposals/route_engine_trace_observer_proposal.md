# 경로 엔진 관찰자 훅 도입 제안

> 상태: Proposal
>
> 기준일: 2026-09-12
>
> 관련 코드: `src/route_engine/engines/circular_beam.py`, `src/route_engine/engines/oneway_beam.py`, `src/route_engine/engines/path_utils.py`, `src/route_engine/engines/waypoint_engine_assembly.py`, `visualizations/route_trace.py`, `visualizations/waypoint_trace.py`
>
> 결정 담당: 경로 엔진 영역 담당자

이 문서는 제안이며 구현하지 않았다. 승인 전까지 시각화는 지금처럼 `sys.settrace` 수집 + 어댑터로 동작한다.

## 1. 왜 지금 정해야 하는가

시각화는 "엔진이 실제로 무엇을 했는가"를 보여준다. 그러려면 엔진 내부의 후보·선택·기각·경로 변경을 밖에서 읽어야 한다. 지금은 `sys.settrace`로 엔진 함수의 지역 변수를 훔쳐본다. 이 방식은 **엔진 코드 구조가 바뀌면 깨진다.**

이번 PR에서 시각화 쪽은 어댑터 계층으로 분리했다. 화면과 스토리 생성은 더 이상 settrace 산출물을 직접 보지 않고, 어댑터가 낸 공통 이벤트(`visualizations/events.py`)만 본다. 그래서 **입력만 바꾸면 settrace를 훅으로 갈아끼울 수 있다** — 어댑터·이벤트 형식·화면은 그대로 둔 채.

## 2. 지금 settrace가 읽는 지점

`visualizations/route_trace.py`(Beam)와 `visualizations/waypoint_trace.py`(GRASP 계열)가 아래 함수의 프레임을 건다. 괄호 안은 읽는 지역 변수다.

| 대상 함수 | 읽는 지점 | 읽는 값 | 만들어지는 기록 |
|---|---|---|---|
| `CircularBeamEngine._find_start_to_waypoint`<br>`OnewayBeamEngine._find_start_to_waypoint` | `beams = candidates[:_BEAM_WIDTH]` 대입 직후(구문 검색으로 줄 번호를 찾는다) | `candidates`, `beams`, `finished` | `expand`, `keep` |
| `CircularBeamEngine.find_path`<br>`OnewayBeamEngine.find_path` | 반환 시점 | 반환된 후보 목록 | `selection` |
| `PathUtils.connect_to` | 반환 시점 | 반환된 완성 경로 | `connect` |
| `PathUtils.prune_dead_ends` | 반환 시점 | `path_nodes`(정리 전), 반환값(정리 후) | `prune` |
| `grasp_waypoint_common.construct_initial_route` | `step_d = ...` 대입 줄, 반환 시점 | `waypoints`, `rcl`, `chosen`, `i`, 반환 `BuildResult` | `grasp_choice`, `constructed`, `construction_failed` |
| `waypoint_local_search.local_search`<br>`waypoint_refinement.vnd` | `better(neighbor_obj, best_neighbor_obj)` 조건 줄, `(current, current_obj) = ...` 대입 줄 | `neighbor`, `current`, `current_obj`, `best_neighbor_obj`, `idx` | `neighbor`, `improved` |
| `waypoint_refinement._shake` | 반환 시점 | `route`, `shake_level`, 반환값 | `shake`, `shake_failed` |
| `waypoint_refinement.vns_loop` | `better(candidate_obj, current_obj)` 조건 줄 | `candidate`, `candidate_obj`, `current`, `current_obj`, `shake_level` | `vns_decision` |
| `waypoint_alns._destroy` / `_repair` | 반환 시점 | `ids`, `method`, 반환값 | `destroy`, `repair` |
| `waypoint_alns._accept` | 반환 시점 + 호출자 프레임 | `delta`, `temperature`, 호출자의 `candidate`·`current` | `alns_accept` |
| `waypoint_refinement.alns` | 반환 시점 | `route`, `improved`, `accepted`, `new_waypoints`, `target_m`, `tolerance` | `alns_result` |
| `WaypointEngine.find_path` | `(best_obj, best_route) = ...` 대입 줄 | `obj`, `best_obj`, `best_route` | `winner` |

### 현재 취약점

1. **변수 이름과 구문 구조에 묶인다.** `beams`·`candidates`·`rcl`·`chosen` 같은 지역 변수 이름을 바꾸거나, `better(...)` 조건식을 다른 형태로 쓰면 계측 지점을 못 찾는다. 지금은 `ast`로 구문을 찾고 **함수 소스 해시를 결과에 남겨**(`trace_source_hashes`) 구조 변경을 감지한다. 감지되면 오류로 멈추므로 잘못된 장면이 나오지는 않지만, **엔진을 고칠 때마다 시각화가 깨진다.**
2. **디버거·커버리지와 같이 못 쓴다.** `sys.settrace`는 하나뿐이라 기록 실행 중에는 디버거를 붙일 수 없다(`SearchTrace.__enter__`가 다른 trace가 걸려 있으면 거부한다).
3. **느리다.** 모든 파이썬 줄마다 콜백이 걸린다. 그래서 시간 측정은 기록을 끈 실행에서 따로 한다.
4. **호출자 프레임까지 읽는다.** `alns_accept`는 `frame.f_back.f_locals`로 호출자의 지역 변수를 읽는다. 호출 구조가 바뀌면 조용히 다른 값을 읽을 위험이 가장 큰 지점이다.

## 3. 제안: 관찰자 훅

엔진 생성자에 선택 인자 `observer`를 받고, 위 지점에서 `observer`가 있을 때만 콜백을 부른다.

```python
class CircularBeamEngine:
    def __init__(self, inp, G, ..., observer: Optional[TraceObserver] = None):
        ...
        self.observer = observer
```

호출은 전부 같은 형태다.

```python
beams = candidates[:_BEAM_WIDTH]
if self.observer is not None:
    self.observer.on_candidates(...)
```

`observer=None`이면 `if self.observer is not None` 검사 한 번 외에 비용이 없고 반환 결과도 바뀌지 않는다.

### 인터페이스 시그니처

`visualizations/events.py`의 공통 어휘(`kind`)와 1:1로 맞춘다. 훅 이름이 곧 `kind`다.

| 훅 | 시그니처 | 부르는 지점 | 지금 대응하는 기록 |
|---|---|---|---|
| `on_run_start` | `(start, end, target_m, settings: dict)` | `find_path` 시작 | 어댑터가 만들던 `run_start` |
| `on_candidates` | `(stage: str, candidates: list, values: dict)` | Beam 확장 직후, GRASP RCL 구성, ALNS `destroy`·`repair` 직후 | `expand`, `grasp_choice`, `destroy`, `repair` |
| `on_select` | `(stage: str, chosen: list, reason: str, values: dict)` | Beam 상위 k 절단, GRASP 경유지 선택, `winner`, `vns_decision`(채택), `alns_result`(채택) | `keep`, `grasp_choice`, `winner`, `vns_decision`, `alns_result` |
| `on_reject` | `(stage: str, dropped: list, reason: str, values: dict)` | Beam 절단 탈락분, 구축 실패, 교란 실패, `vns_decision`·`alns_result`(기각) | `drop`, `construction_failed`, `shake_failed` |
| `on_evaluate` | `(stage: str, candidate, values: dict)` | 이웃 후보 검토, ALNS 내부 수락 판단, 정제 종료 | `neighbor`, `alns_accept`, `refinement_done` |
| `on_route_changed` | `(stage: str, before: list, after: list, values: dict)` | 연결 완성, 초기 경로 구축, 개선 채택, 교란 | `connect`, `constructed`, `improved`, `shake` |
| `on_cleanup` | `(stage: str, before: list, after: list)` | `PathUtils.prune_dead_ends` 반환 직전 | `prune` |

`stage`는 지금의 `phase`와 같은 이름을 쓴다. 화면이 이미 그 이름으로 설명 문구를 고르므로 그대로 두면 재생 화면을 고치지 않아도 된다.

`values`에 담는 값은 지금 settrace가 읽는 값과 같다. 예를 들어 Beam의 `on_candidates`는 `{"iteration", "generated", "kept", "finished"}`, `on_evaluate`(ALNS 내부 수락)는 `{"delta", "temperature", "accepted", "internal_before", "internal_after"}`다. 어댑터의 매핑표(`visualizations/beam_adapter.py`·`waypoint_adapter.py` 모듈 docstring)가 그 대응을 그대로 갖고 있다.

### 훅이 들어오면 달라지는 것

- `visualizations/route_trace.py`, `visualizations/waypoint_trace.py`가 사라진다(settrace 제거).
- `visualizations/beam_adapter.py`, `visualizations/waypoint_adapter.py`는 **입력만 바뀐다**. 매핑 규칙·`candidate_id` 규칙·`decision.reason` 문장은 그대로다.
- `trace_source_hashes`(소스 해시 검사)가 필요 없어진다. 훅은 계약이라 구조가 바뀌어도 조용히 깨지지 않는다.
- 기록 실행에서도 디버거·커버리지를 같이 쓸 수 있다.

## 4. 배포 코드에 남는 이유

이 작업의 훅과 인자는 임시 계측이 아니라 **엔진의 정식 계약**이다. 배포 전에 걷어내야 할 코드가 아니며 "임시"라고 부르지 않는다.

- `observer=None`은 정식 생성자 인자다. `None`이면 `if self.observer is not None` 검사 한 번 외에 비용이 없고 반환 결과가 바뀌지 않는다.
- 같은 패턴의 선례가 이미 있다: `src/route_engine/engines/oneway_astar.py`의 `heuristic=None` 인자([PR #421](https://github.com/ChimaekMeeting/seoul-walk-platform/pull/421)). 서비스는 인자 없이 쓰고 시각화·벤치마크만 넘긴다. 그 인자에도 "배포 코드에 남는 정식 인자"라고 주석을 달아 두었다.
- 반대로 `sys.settrace` 기반 수집(`SearchTrace`, `WaypointTrace`)은 **오프라인 전용**이고 서비스 요청 중에는 절대 켜지 않는다. 두 모듈의 첫 줄에 그렇게 적혀 있다. 훅이 들어오면 이쪽이 사라진다.
- 계측 A* 복제본(`benchmarks/runner/_astar_instrumented.py`)도 벤치마크·시각화 전용이며 `src/**`는 이 파일을 import하지 않는다.

## 5. 적용 순서 제안

1. **서비스 엔진 먼저**: `CircularBeamEngine`, `OnewayBeamEngine`과 `PathUtils.connect_to`·`prune_dead_ends`. 서비스에 연결된 엔진(`RouteService.base_engines`)이라 계약이 안정적이고, 시각화에서 가장 자주 보는 화면이다.
2. **GRASP 계열은 그다음**: `WaypointEngine`과 정제 함수들. 아직 서비스에 연결되지 않았고(`service_use="benchmark_only"`) 구조 변경이 잦으므로, 담당자의 작업이 안정된 뒤에 넣는다.
3. 각 단계가 끝나면 해당 어댑터의 입력만 바꾸고 회귀 테스트(`visualizations/tests`)로 같은 이벤트가 나오는지 대조한다.

## 6. 결정 요청 항목

경로 엔진 영역 담당자가 정해 주면 시각화 쪽에서 어댑터 입력을 맞춘다.

1. **훅 이름**: 위 표의 `on_candidates`/`on_select`/`on_reject`/`on_evaluate`/`on_route_changed`/`on_cleanup`/`on_run_start`를 그대로 쓸지, 엔진 쪽 용어로 바꿀지.
2. **넘기는 값의 형**: `dataclass`(예: `TraceEvent`)로 고정할지, `dict`로 느슨하게 둘지. dataclass면 계약이 분명해지고 오타가 잡히지만 엔진이 시각화용 타입을 import해야 한다. dict면 의존이 없지만 키 이름이 계약이 된다.
3. **어느 엔진부터**: 위 순서(서비스 Beam → GRASP)를 그대로 쓸지, 다른 순서가 좋은지.
4. **벤치마크 성능 영향 측정 방법**: `observer=None`일 때 비용이 실제로 무시할 수준인지 무엇으로 확인할지(예: `benchmarks/runner`의 기존 점대점 벤치마크를 훅 도입 전후로 같은 입력·반복 횟수로 돌려 비교).
5. **`PathUtils`의 위치**: `connect_to`·`prune_dead_ends`는 엔진이 아니라 유틸이다. 관찰자를 `PathUtils` 생성자로 받을지, 호출부(엔진)가 반환값을 받아 직접 알릴지.

## 7. 승인 전까지의 동작

- 시각화는 `sys.settrace` 수집 + 어댑터로 동작한다. 실행 방법과 검증은 [알고리즘 시각화 실행](../operations/algorithm_visualization.md)에 있다.
- 엔진 코드 구조가 바뀌어 계측이 깨지면 시각화 실행이 오류로 멈춘다. 잘못된 장면을 만들지는 않는다.
- 이 문서가 승인되면 상태를 `Current`로 바꾸지 않고, 구현 PR에서 영역 계약(`docs/route_engine/README.md`)에 훅 계약을 추가한 뒤 이 제안을 `Archive`로 내린다.
