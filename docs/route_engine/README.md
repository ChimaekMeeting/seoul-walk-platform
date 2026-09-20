# 경로 생성 엔진

> 상태: Current
> 기준일: 2026-09-20
> 관련 코드: `src/route_engine/`

경로 생성 엔진은 외부 API나 챗봇 처리와 분리된 경로 계산 영역입니다.

(2026-09-19 갱신) 안전·편안 축소(8축→safety/comfort 2축)와 함께 `src/route_engine/graph/`
폴더(그래프 준비·필터·직렬화 계층)와 `src/route_engine/profiles.py`(`ScoringProfile`/
`get_profile()`/`blocked_tags`)가 전부 삭제됐다. `GraphRepository`(`src/repository/network/`)가
NetworkX Graph를 직접 만들고, 선호도는 route_engine이 아니라 챗봇/스키마 계층의
`Weights`(`src/schema/route_schema.py`, `safety`/`comfort` 두 필드)로만 표현한다.

## 현재 구조

| 구성요소 | 위치 | 역할 |
|---|---|---|
| Scoring | `src/route_engine/scoring/` | WalkEdge 속성(safety/accident/slope score)을 경로 비용으로 계산 |
| Engine | `src/route_engine/engines/` | 순환·편도 경로 탐색 알고리즘 |
| Waypoint Search | `src/route_engine/waypoint_beam.py` | 외부 후보·거리 함수로 경유지 선택 및 순서 탐색(API 미연결) |
| Waypoint Improvement | `src/route_engine/waypoint_alns.py` | 외부 초기 경유지 순서를 받아 선택·순서를 개선(API 미연결) |
| Waypoint Evaluation | `src/route_engine/waypoint_evaluation.py` | 도로 재통행 측정과 Beam·ALNS 공통 비교 기준 |

## 계약 문서

- [경로 그래프 계약](graph_contract.md)

## 경유지 Beam Search 독립 함수 (2026-08-30)

진입점은 [waypoint_beam.py](../../src/route_engine/waypoint_beam.py)의
`beam_search()`이다. 기존 `engines/`의 도로 노드 탐색이나
`WaypointComposerEngine`의 구간 연결을 대체하지 않는다. `RouteService` 및
API에는 연결하지 않았으며, 아래 기존 Engine의 `run()` 반환 계약과 별개이다.

### 입력·출력·의존성

- `candidates`: `node_id: int`, `lat: float`, `lon: float`를 가진 후보 목록.
  필수 키와 정수 ID를 검사하고, 중복 ID는 `ValueError`로 거부한다.
  좌표로 다시 스냅하지 않으며 입력을 변경하지 않는다.
- `cost(a, b) -> float`: 동일한 그래프에서 계산한 대칭인 순수 거리(m).
  도달 불가는 양의 `inf`; 음수·NaN·음의 inf는 거부한다.
  그래프 버전 일치, 거리의 대칭성 및 lazy 캐시는 제공자 책임이다.
  임의 custom score로 교체하면 거리(m) 평가 의미가 달라지므로 이 계약을 재검토해야 한다.
- `start_id`, `end_id`, 양수 `target_m`, 양의 정수 `waypoint_count`(N),
  `beam_width`(B)를 명시적으로 받는다. 순환은 `end_id=start_id`로 호출한다.
  출발·도착은 후보 선택 대상에서 제외하고, 남은 후보 수가 N보다 작으면 거부한다.
  편도 후보 풀의 적절성은 제공자가 보장해야 하며, 순환용 cutoff 풀을 자동 전용하지 않는다.
- 반환 `BeamResult.orders`: 최대 B개의 `WaypointOrder`. 기본 모드는 `(error_m, waypoint_ids)`
  오름차순이며, 재통행 모드는 아래 공통 평가 기준을 사용한다. `waypoint_ids`는 출발·도착을 제외한 정확히 N개의 중복 없는 ID 튜플이고,
  `distance_m`는 출발부터 도착까지 구간 cost의 합, `error_m`는 목표와의 절대 차이다.
  이는 실제 도로 노드열이나 `WalkRouteResponse`가 아니다.
- `evaluated_candidates`: 미선택 후보를 붙이려 시도한 횟수(inf로 제외된 시도 포함).
  `cost_calls`: 캐시 적중 여부와 무관한 callback 호출 수이며 A* 실행 횟수가 아니다.
- 탐색에서 완성 조합을 찾지 못하면 `orders=()`와 측정값을 반환한다.
  이는 전역적으로 해가 없다는 증명이 아니다. 호출자가 실패 메시지를 처리한다.
  cost 제공자의 예외는 숨기지 않고 전달한다.
- 표준 라이브러리만 사용한다. 후보 생성·그래프 로딩·DB·스냅·A* 복원은 수행하지 않는다.
  ALNS와 GRASP는 호출하지 않으며, 다른 알고리즘과의 출력 변환은 아직 연결하지 않았다.

### 구현한 탐색 규칙과 참고 범위

1. 현재 부분 경유지 순서마다 미선택 후보 하나를 붙인다.
2. `partial_m`에 새 구간 cost를 더하고, `closed_m = partial_m + cost(마지막, 도착)`으로 평가한다.
   앞 단계의 임시 복귀 구간은 `partial_m`에 넣지 않아 다음 단계에 중복 합산되지 않는다.
3. 모든 부모의 확장 결과에서 `abs(closed_m - target_m)`가 작은 전역 Top-B를 남긴다.
   동점은 경유지 ID 튜플 순서로 결정한다. 마지막 ID가 같아도 다른 순서는 합치지 않는다.
4. N개를 선택할 때까지 반복하고 최종 생존 조합을 반환한다.

- [TLMR](https://link.springer.com/article/10.1007/s40747-024-01611-z)의 부분 경로에
  다음 노드를 붙이는 구조를 경유지 순서 확장에 응용했다. 학습 모델·누적 확률·부모별 상위 n개 선택은 구현하지 않았다.
- MS-Pointer는 [팀 Beam Search 노션 정리](https://app.notion.com/p/Beam-search-3c7295569fdc8099bcecf5ac0eb57291)의
  전역 Top-B 반복 구조를 참고했다. 2026-08-30 제공된 원문 PDF 6쪽 Table 2와도 대조했다.
  신경망 점수 모델과 논문 전체를 재현한 것은 아니다.
- 목표 거리 평가식, 고정 N, ID 동점 처리는 본 프로젝트의 구현 규칙이다.
  중간 `closed_m`은 지금 도착지로 연결할 경우의 거리일 뿐, N개 선택 후 거리의 예측 보장이나
  최적 오차의 하한이 아니다. Beam 가지치기는 최적해를 놓칠 수 있다.
- 부모별 후보 제한 q, 목표 초과 가지치기, 별도 pairwise 거리표는 없다.
  generator와 `nsmallest`로 확장 상태 전체의 저장은 피하지만 모든 확장 후보는 평가한다.
  따라서 후보 풀이 크면 B가 작아도 거리 계산이 오래 걸릴 수 있다.
- 경유지 중복 선택 금지는 실제 도로 구간 재방문 금지가 아니다.
  역방향 순환 순서도 별도 후보로 남을 수 있으므로 반환 개수가 경로 다양성을 보장하지 않는다.
  기본 거리 전용 모드에서는 목표 허용 오차를 호출자가 판정한다.
  재통행 모드는 별도 도로 평가 공급자를 통해 아래 공통 평가를 사용한다. 경로 다양성은 보장하지 않는다.

### 실행·검증·복구

저장소 루트의 Git Bash에서 API나 DB를 띄우지 않고 실행한다.

```bash
./.venv/Scripts/python.exe -m pytest --noconftest tests/unit/test_waypoint_beam.py -q
```

- 2026-08-30, Windows 로컬 Python 3.12.13 / pytest 8.4.2에서
  [단위 테스트](../../tests/unit/test_waypoint_beam.py) 72개 통과.
  작은 거리표의 전체 순열 비교, 전역 Top-B와 독립 기준 구현 비교, 복귀 거리 중복 합산 방지,
  결정성·입력 보존·inf·입력 오류·호출량을 검증했다.
- `--noconftest`로 기존 테스트의 DB mock 및 자동 환경변수 주입 없이도 통과했다.
  Python `-S` 환경에서 독립 import도 확인했다.
- 같은 환경에서 기존 `test_graph_artifact_repository.py`, `test_runtime_graph_loading.py`,
  `test_path_utils.py`만 별도 실행하면 31개 통과·3개 실패했다.
  실패는 `safety_score` 누락을 거부해야 한다는 artifact 테스트 1건과
  빈 그래프/좌표 없는 노드의 최근접 노드 처리 테스트 2건이다.
  해당 기존 코드·테스트는 이번 작업에서 변경하지 않았고 신규 Beam 테스트 없이도 재현했다.
- 실제 artifact 규모의 성능, 다연님 실제 후보/거리 모듈 연결, ALNS/GRASP 연결,
  실제 도로 경로 복원 및 API Workflow는 아직 검증하지 않았다.
- 문제 발생 시 신규 함수 호출부와 이 단위 테스트부터 확인한다. 기존 서비스 연결과
  DB·artifact 변경이 없으므로 이 함수의 사용을 중지하는 데 데이터 복구는 필요하지 않다.

## 경유지 ALNS 독립 함수 (2026-08-30)

진입점은 [waypoint_alns.py](../../src/route_engine/waypoint_alns.py)의 `alns_search()`이다.
Beam 알고리즘을 호출하지 않으며, 외부에서 완성한 초기 경유지 순서를 받는다.
기존 Engine·서비스·DB·API는 변경하지 않았다.

### 입력·출력과 공유 자료형

- `candidates`, `cost`, `start_id`, `end_id`, `target_m`의 의미는 위 Beam 계약과 같다.
- `initial_ids`는 출발·도착을 제외한 중복 없는 경유지 ID 순서다. 초기 해의 개수 N을 유지한다.
  N을 별도 입력받거나 자동으로 선택하지 않는다. 초기 해는 후보 풀에 속하고 도달 가능해야 한다.
  저장된 초기 거리값을 신뢰하지 않고 동일한 `cost`로 다시 계산한다.
- [waypoint_types.py](../../src/route_engine/waypoint_types.py)에 `WaypointCandidate`,
  `CostFunction`, `WaypointOrder`를 모았다. Beam의 기존 import 경로에서도 해당 이름을 사용할 수 있다.
  이는 현재 두 모듈의 내부 공유 표현이며, 아직 팀원 GRASP의 실제 반환 계약과 합의·연동한 것은 아니다.
- `ALNSResult.best`는 초기 해와 복구 완료 후보 중 설정된 품질 기준이 가장 좋은 조합이다.
  `current`는 마지막 수락 조합이므로 best보다 나쁠 수 있다. 기본 모드는 최저 거리 오차,
  재통행 모드는 아래 공통 평가를 사용하며 품질 동점에는 best를 교체하지 않는다.
- `iterations`는 착수한 시도 수, `evaluated_orders`는 초기 해·중간 삽입을 포함한 평가 착수 수다.
  `cost_calls`는 실제 callback 호출 수이며 캐시 적중을 포함한다.
  `accepted_moves`, `failed_repairs`, 연산자별 전체 사용 횟수·현재 가중치도 반환한다.
- 종료 이유는 `iterations`, `cost_budget`, `exact_target`, `exact_target_no_overlap`이다.
  기본 모드는 오차 0, 재통행 모드는 거리 오차와 재통행이 모두 0일 때만 조기 종료한다.

### 기본 거리 전용 모드의 구현 규칙

1. 제거 수는 `ceil(N * removal_fraction)`(최소 1)이다. 현재 해에서 무작위 제거 또는 연속 구간 제거를 한다.
   순환에서는 끝·처음 경유지를 연결한 구간도 허용하고, 편도에서는 끝을 넘어가지 않는다.
2. 제거된 경유지와 아직 선택하지 않았던 후보를 모두 삽입 대상으로 허용한다.
   `candidate_limit`가 있으면 cost 호출 전에 이번 복구의 후보를 균등 표본추출한다.
   표본 수는 제거 수 이상이어야 하며, 제외한 후보를 대신 평가하지는 않는다.
3. Greedy repair는 후보·삽입 위치 전체에서 삽입 후 목표 거리 오차가 가장 작은 것을 선택한다.
   Random-order repair는 후보 순서를 섞고, 첫 삽입 가능한 후보의 최저 오차 위치를 선택한다.
   둘 다 N개가 될 때까지 반복하며 동점은 ID 순서로 처리한다. 중간 삽입 평가는 탐욕적이며 최적 복구를 보장하지 않는다.
4. N개 복구에 실패하면 해당 시도를 버리고 current와 best를 유지한다. 이는 전역적인 해 부재 증명이 아니다.
   초기 해의 도달 불가는 `ValueError`, cost 제공자 예외·음수·NaN 등은 숨기지 않고 전달한다.
5. 현재 해보다 오차가 작거나 같으면 수락하고, 크면 `exp(-오차증가 / T)` 확률로 수락한다.
   `T`는 `start_temperature_m`에서 시작해 매 완료 시도마다 `cooling_rate`를 곱한다.
   T=0은 악화 해를 수락하지 않는 비교 실험용 설정이다.
6. Destroy·Repair를 각각 독립적으로 가중 룰렛 선택한다. 처음 수락한 조합에 한해
   전역 최적 갱신 6점, 현재 해 개선 3점, 그 외 수락 1점을 양쪽 연산자에 동일하게 준다.
   동일·이미 수락한 조합, 거절 및 복구 실패는 0점이다.
7. `segment_length`회마다 `w = (1-r)*w + r*(누적점수/사용횟수)`로 갱신한다.
   미사용 연산자는 유지하고 가중치 하한은 1e-6이다. 미완료 segment는 다음 선택이 없으면 갱신하지 않는다.
8. `max_cost_calls`는 초기 해 평가까지 포함한 호출 한도다. 진행 중 예산이 끝나면 미완료 복구를 폐기하고
   이전까지의 best를 반환한다. 한 번의 cost 호출 소요 시간을 제한하는 타임아웃은 아니다.

기본 매개변수와 6/3/1 보상은 실험 시작용 설계값이며 논문에서 검증된 보행 서비스 튜닝값이 아니다.
`iterations=200`, `removal_fraction=0.3`, `start_temperature_m=100`, `cooling_rate=0.99`,
`segment_length=20`, `reaction_factor=0.2`는 구현 시 선택한 미튜닝 기본값이다.
None으로 둔 후보·호출 제한은 제한을 적용하지 않는다는 뜻이고 seed=0은 재현용 식별값이다.
수식의 근거와 이 숫자들의 근거는 구분한다. 원문 §3.4의 segment 길이는 100회이며,
§3.5의 초기 온도는 초기 해를 기준으로 계산하므로 현재 기본값을 원문 매개변수로 소개하지 않는다.
N=3에서 removal_fraction=0.3이면 1개만 제거하므로 두 제거 방식의 차이가 작다.
제거 방식 비교에서는 제거 수 2 이상인 설정도 함께 시험해야 한다.
별도 pairwise 캐시는 없고 구간을 다시 합산한다. 따라서 큰 후보 풀은
`candidate_limit`·`max_cost_calls`와 외부 거리 캐시를 사용해 계산량을 관리해야 한다.
Feature·rollout·ALNS 뒤의 별도 지역 탐색은 구현하지 않았다.
도로 재통행은 아래 선택적 공통 평가 모드에서 처리한다.

### 논문과 노션의 적용 범위

- [팀 ALNS 노션](https://app.notion.com/p/ALNS-3c7295569fdc8058ae14cea92dfcf83a)을 API로 조회하고
  제공된 원문 세 편의 관련 절·수도 코드와 대조했다.
- Paul Shaw (1998), *Using Constraint Programming and Local Search Methods to Solve Vehicle Routing Problems*,
  §2: 제거·재삽입 LNS 구조를 참고했다. 관련도 제거, CP, branch-and-bound, LDS는 구현하지 않았다.
- Røpke & Pisinger (2006), DOI `10.1287/trsc.1050.0135`, 제공 기술보고서 PDF 6, 9–11쪽:
  Algorithm 1, §3.2.1 Greedy, §3.3–3.5 룰렛·segment 가중치·SA를 참고했다.
  픽업/배송·시간 창·차량 제약, regret 삽입은 구현하지 않았다.
  초기 온도는 원문의 초기 목적값 비례 계산 대신 m 단위 명시 입력을 받는다.
  새로운 동점 해에도 1점을 주는 것은 본 구현의 선택이다.
- Santini (2019), DOI `10.1016/j.eswa.2018.12.050`, PDF 6–9쪽 §4:
  무작위·연속 구간 제거와 미선택 후보를 삽입하는 구조를 참고했다.
  Random repair는 무작위 비율만큼 삽입하는 원문과 달리 N개까지 채우며, 삽입 위치는 목표 거리 오차로 정한다.
  보상값·군집·시간 상한·Lin-RRT·매 반복 가중치 갱신·2OptFill 등은 구현하지 않았다.

### 실행·검증·복구

```bash
./.venv/Scripts/python.exe -m pytest --noconftest tests/unit/test_waypoint_beam.py tests/unit/test_waypoint_alns.py -q
./.venv/Scripts/python.exe -m benchmarks.runner.waypoint_beam --repeats 3
./.venv/Scripts/python.exe -m benchmarks.runner.waypoint_alns --seeds 0 1 2
```

- 2026-08-30 Windows 로컬 Python 3.12.13 / pytest 8.4.2: Beam 72개 + ALNS 78개 = 150개 통과.
- ALNS 테스트는 제거 개수·순서, 후보 교체, 실제 거리 재합산, SA, best 보존, segment 갱신,
  seed 재현성·입력 보존, 실패 처리, 호출 한도, 작은 거리표 전수 비교를 포함한다.
- 같은 날 실행기 이동 후 위 150개와 `benchmarks/tests/test_waypoint_runners.py` 7개,
  합계 157개 통과. 공통 후보 재현·반복 시 캐시 초기화·설정 기록·실행 인자 오류를 추가 검증했다.
- [ALNS 실행기](../../benchmarks/runner/waypoint_alns.py)는 실제 artifact에서 검증용 후보 12개를 골라
  같은 Beam 초기 해를 seed마다 빈 거리 캐시로 개선한다. 거리 공급자는 NetworkX 최단거리와 최대 1024쌍 LRU다.
  팀원 후보 생성 모듈·A* 구현과의 통합 테스트가 아니라 제한된 실제 거리 연결 검증이다.
- [Beam 실행기](../../benchmarks/runner/waypoint_beam.py)는 Beam만 빈 거리 캐시에서 반복 측정한다.
  두 실행기는 [공유 준비 코드](../../benchmarks/runner/_waypoint_common.py)로 같은 후보·거리 함수를 사용한다.
  준비 시간은 측정에서 제외하며, ALNS 시간은 Beam 초기 해 생성 시간도 제외한다.
  현재 실행기의 후보 준비는 순환 검증용이다. 알고리즘 자체의 편도 지원과 구분한다.
  기존 `benchmarks.benchmark`는 실제 도로 노드열을 받으므로 이 실행기를 해당 registry에 등록하지 않았다.
  경유지 순서를 도로 노드열로 간주하면 품질 지표가 잘못 계산된다.
  ALNS 설정은 `--removal-fraction`, `--start-temperature-m`, `--cooling-rate`,
  `--segment-length`, `--reaction-factor`, `--candidate-limit`로 변경하고 JSON 출력에도 기록한다.
  설정을 바꾸지 않은 실행의 계산 규칙·기본 수치는 이전 scripts 실행기와 같다.
- 해당 일자 로컬 관측: v2-2026-08-25 artifact(160197 노드 / 223693 엣지), 시작 ID 1,
  목표 3000m, N=3, B=2, ALNS 30회, 호출 한도 20000. 초기 오차 23.524m에서
  seed 0은 5.614m, seed 1·2는 23.524m였다. ALNS 시간은 약 0.19–0.28초로,
  artifact 로드·후보 추출·Beam 생성 시간을 제외한다. 고정 기대값이나 전체 후보 풀 성능 보장이 아니다.
- 미확인: 실제 팀원 모듈·GRASP·API 연결, 전체 후보 풀에서의 성능 및 서비스 품질.
- 실패 시 이 독립 함수와 단위 테스트부터 확인한다. 데이터·API를 변경하지 않아 DB 복구는 필요 없다.

## Beam·ALNS 도로 재통행 평가 (#380, 2026-08-30)

### 입력·출력과 경계

- [공통 평가기](../../src/route_engine/waypoint_evaluation.py)의 `RouteEvaluator`는
  `path(a, b) -> 노드 ID 열 | None`과 `edge_length(u, v) -> 거리(m)`를 외부에서 받는다.
  path는 양 끝점을 포함하며, None은 도달 불가다. 기타 공급자 예외는 숨기지 않는다.
- path와 기존 `cost(a, b)`는 **동일한 고정 무방향 단순 그래프와 거리 기준**을 사용해야 한다.
  `attach_route_metrics()`는 구간 cost 합과 복원된 실제 거리의 일치를 검사한다
  (부동소수점 비교 rel_tol=1e-9, abs_tol=1e-6m).
  이 일치 검사는 단위 오류를 잡는 장치이며 그래프 버전의 동일성을 증명하지는 않는다.
- 경유지 순서를 출발·도착 포함 `stops`로 만들어 평가한다. 역방향도 같은 도로로 정규화하고,
  두 번째 이후 통행 거리만 누적한다. `RouteMetrics(distance_m, repeated_m)`와
  `overlap_ratio = repeated_m / distance_m`를 반환한다. 이동 거리 0은 비율 0으로 정의한다.
  단순 왕복은 50%, 재통행 없는 순환은 0%다.
- 같은 노드 쌍의 경로는 낮은 ID에서 높은 ID로 한 번 정해 역방향에도 사용한다.
  최단경로 동점 선택을 고정하기 위한 규칙이다. 지도에 최종 경로를 그리는 연결부도 같은
  구간 선택 규칙을 사용해야 평가한 경로와 일치한다. API·렌더러에는 아직 연결하지 않았다.
- 도로 식별자는 `(min(u,v), max(u,v))`다. 평행 도로를 가진 MultiGraph나
  서로 다른 ID로 표현된 동일 지리 구간까지 식별하는 구현은 아니다.
- 구간 LRU 기본 상한은 1024쌍이며 0으로 캐시를 끌 수 있다. 전체 후보 쌍을 미리 계산하지 않는다.
  이것은 **항목 수 제한이지 메모리 바이트 제한이 아니다**. 긴 구간에는 더 많은 메모리가 든다.
  그래프를 교체하면 평가기도 다시 만든다. 실행 중 그래프·가중치를 변경하지 않는다.
- `WaypointOrder.route_metrics=None`은 평가하지 않음을 뜻한다. 재통행 0%로 간주하지 않는다.
  기존 세 인자 생성과 거리 전용 Beam·ALNS 호출은 유지된다.
- 재통행 모드는 `tolerance_ratio`와 `evaluate_route`를 함께 지정한다.
  허용 오차 기본값은 없고 0 이상 1 미만의 비율을 명시적으로 받는다.
  기존 `cost()` 반환 단위나 의미는 변경하지 않았다.

### 공통 비교와 수락 기준

목표 대비 거리 오차를 e, 재통행 비율을 r이라 할 때:

| 조건 | 주 점수 (낮을수록 좋음) | 주 점수 동점 비교 |
|---|---|---|
| 거리 전용 | 거리 오차(m) | ID 순서 |
| 허용 범위 안 | r | e, ID 순서 |
| 허용 범위 밖 | 1 + e | r, ID 순서 |

- 허용 범위는 `error_m <= target_m * tolerance_ratio`로 양 끝을 포함한다.
  범위 안의 r은 0~1이고 밖의 점수는 1보다 커서, 범위 만족이 우선된다.
  범위 안에서는 재통행 비율이 같을 때만 거리 정확도를 비교한다.
  재통행 감소를 위해 거리 오차가 이전보다 늘어나는 결과도 의도된 동작이다.
- 이 점수화·허용 범위 정책은 본 프로젝트의 설계이며 논문에서 가져온 공식이 아니다.
  [Lewis·Corcoran(2024)](https://link.springer.com/article/10.1007/s42979-024-03223-3)의
  거리 오차와 재통행 비율이라는 두 평가 대상을 참고했다. 논문의 Pareto 탐색은 구현하지 않았다.
  공개 서비스 [RunWeather](https://www.runweather.org/)의 2.5%·7.5% 설정은 비교 구간의 참고 사례일 뿐
  산책자의 만족도를 검증한 표준이 아니다. 5% 역시 실험 비교값이며 서비스 기본값으로 확정하지 않았다.
- Beam은 **각 단계 Top-B 선정 전** 새 경유지 순서를 지금 도착지로 연결해 평가한다.
  이전 단계의 임시 복귀 경로는 다음 단계에 누적하지 않는다.
  부분 경로의 평가는 최종 결과의 예측 보장·하한이 아니므로 최적해를 버릴 수 있다.
- ALNS는 중간 삽입 후보에도 같은 기준을 사용하고, N개 복구를 마친 조합만 현재/최적 해에 반영한다.
  최적 해 갱신·개선 보상에는 주 점수와 동점 비교값을 함께 사용한다(ID만 바뀐 것은 개선 아님).
- SA의 delta는 **주 점수 증가량**이다. delta<=0이면 수락하고, 양수이면 `exp(-delta/T)`를 쓴다.
  주 점수 동점이면 보조 품질이 나빠져도 중립 이동으로 수락할 수 있으며 best는 별도로 유지한다.
  이는 사전식 튜플 전체를 단일 실수로 바꾼 SA가 아니라 주 점수에 적용한 SA다.
- 거리 전용의 `start_temperature_m`는 유지한다. 재통행 모드는 무차원
  `start_temperature_score`를 반드시 별도로 지정한다. 아래 명령의 0.05는 실험값이다.
  예를 들어 주 점수 증가 0.05, T=0.05이면 수락 확률은 exp(-1), 약 36.8%다.
- 범위를 충족하고 재통행이 0이어도 거리 동점 비교를 더 개선할 수 있으므로, 재통행 모드는
  **거리 오차=0 및 재통행=0을 동시에 달성한 경우에만** 조기 종료한다.
- 목적함수 추가는 겹침 0% 보장이 아니다. 막다른 길에서는 반복이 필요할 수 있다.
  최단 연결 자체에 방문 이력 페널티를 주거나 기존 서비스 엔진을 수정하지 않았다.

### 재현·검증

```bash
./.venv/Scripts/python.exe -m pytest --noconftest tests/unit/test_waypoint_beam.py tests/unit/test_waypoint_alns.py tests/unit/test_waypoint_evaluation.py benchmarks/tests/test_waypoint_runners.py -q
./.venv/Scripts/python.exe -m benchmarks.runner.waypoint_beam --start-id 1 --target-m 3000 --pool-size 12 --waypoint-count 3 --beam-width 2 --repeats 1 --tolerances 0.025 0.05 0.075
./.venv/Scripts/python.exe -m benchmarks.runner.waypoint_alns --start-id 1 --target-m 3000 --pool-size 12 --waypoint-count 3 --beam-width 2 --iterations 30 --cost-budget 20000 --seeds 0 1 2 --tolerances 0.025 0.05 0.075 --start-temperature-score 0.05
```

- 2026-08-30 Windows 로컬 .venv Python 3.12.13 / pytest 8.4.2:
  위 네 테스트 파일 210개 통과. 기본 동작 회귀, 왕복/순환/길이 가중/역방향,
  허용 범위 경계, Beam 중간 가지치기, ALNS 수락·보상·종료·best 보존, 호출 한도,
  공급자 불일치, 편도·순환 재현성과 비교 실행기의 초기 해 고정을 검증했다.
- 두 실행기는 `--tolerances`를 주면 거리 전용 1개와 지정한 각 비율을 비교한다.
  없으면 기존 거리 전용 실행이다. ALNS 비교에서는 모든 모드가 **같은 거리 전용 Beam 초기 해**를 쓴다.
  `--initial-ids`로 외부 초기 순서를 주면 Beam을 호출하지 않는다. ID는 현재 검증 후보 풀에 속해야 한다.
  팀원 GRASP·후보 생성 모듈과의 실제 연동을 완료했다는 뜻은 아니다.
- 각 실행에서 거리 캐시와 경로 캐시를 초기화한다. 시간에는 탐색 중 재통행 평가가 포함되고
  그래프 로드·후보 준비·ALNS 초기 해 생성·최종 사후 검증은 제외된다.
  `shortest_path_calls`는 기존 거리 공급자 cache miss, `route_path_calls`는 도로 공급자 cache miss,
  `total_search_path_calls`는 두 값의 합이다. `route_evaluations`는 전체 순서 평가 callback 횟수다.
  사후 검증에서 발생한 별도 경로 호출은 `validation_path_calls`로 기록한다.
- 같은 cost 호출 상한이 동일한 실행 시간을 뜻하지 않는다. 겹침 평가는 추가 경로 계산을 수행한다.
  benchmark 출력의 시간과 두 종류의 실제 경로 호출 수를 함께 비교해야 한다.
- 위 명령으로 v2-2026-08-25 artifact(160197 노드, 223693 엣지)의 고정 후보 12개를 사용한 로컬 관측:
  Beam은 거리 전용과 모든 허용 비율에서 거리 3023.524m·재통행 약 3.809%로 같았다.
  ALNS의 seed 0 거리 전용 결과는 2994.386m·재통행 약 8.857%였다.
  2.5% 모드는 seed 0/1/2 모두 초기 해(3023.524m·3.809%)를 유지했고,
  5%·7.5% 모드는 세 seed 모두 약 2908.362m·재통행 0%를 반환했다.
  이는 한 시작점·작은 후보 풀의 관측으로, 일반 품질·최적 허용 비율을 확정하는 근거는 아니다.
  두 실행기는 동시에 실행했으므로 이번 시간 관측을 단독 성능 기준값으로 사용하지 않는다.
- 미검증: 전체 후보 풀의 성능·메모리, 다른 지역/거리에서의 품질, 실제 보행자 만족,
  최종 지도 렌더링 경로의 일치, API Workflow, 팀원 GRASP 연동.
- 복구 시작점: 신규 모드 인자(`tolerance_ratio`, `evaluate_route`,
  `start_temperature_score`)를 함께 생략하면 기존 거리 전용 동작으로 돌아간다.
  DB·artifact·외부 서비스는 변경하지 않았으므로 데이터 복구는 필요 없다.

### 경복궁 시나리오 전수 비교 (2026-08-30)

- 재현 실행기: [waypoint_overlap_audit.py](../../benchmarks/runner/waypoint_overlap_audit.py),
  중간 상태 추적: [waypoint_overlap_diagnostics.py](../../benchmarks/runner/waypoint_overlap_diagnostics.py).
- 보존한 관측 요약: [waypoint_overlap_20260830.json](../../benchmarks/results/waypoint_overlap_20260830.json).
  그래프·코드 해시, 역 좌표와 스냅 ID, 후보 12개, 전수 최적값, 개별 실행 결과를 포함한다.
  원본 도로 노드열·전수 1320개 품질·평가 이력은 실행 시 `tmp/waypoint_overlap_validation/run_<시각>/`에 생성한다.
  중단된 실행과 대용량 임시 결과는 버전 관리에 포함하지 않는다.
- Windows / Python 3.12.13 / NetworkX 3.6 / v2-2026-08-25 artifact에서 관측했다.
  비용은 `length`만 사용하며 재방문 페널티·도로 삭제·왕복 가지 제거는 적용하지 않았다.
- 좌표는 사용자가 제공한 이전 실험 화면에서 가져와 현재 artifact에 스냅했다.
  경복궁 131971, 서대문 78002, 종각 86877이다. 독립적으로 역 출입구 위치를 검증한 것은 아니다.
- 순환 4000m와 편도 3000m 각각 출발 기준 target/2 cutoff 영역을 거리·ID순으로 정렬해
  12개를 균등 간격 표본추출했다. 편도 풀은 팀의 검증된 편도 후보 생성기가 아닌 새 진단 fixture다.
  이전 모델의 편도 실행기·후보 ID 원본이 없어 이전 편도 실패의 재현이라고 설명하지 않는다.
- 각 풀의 12P3=1320개 순서를 NetworkX `shortest_path`와 팀 `PathUtils.astar_path`로 각각 평가했다.
  이번 두 풀에서 canonical 구간 노드열은 모두 일치했다. 다른 입력의 동점 최단경로까지 같다는 보장은 아니다.
  총거리와 추가 통행 거리를 별도 Counter 계산으로 5280개 평가에서 대조했다.
- Beam은 폭 2/8/1320 × 거리 전용/2.5%/5%/7.5%로 총24회 실행했다.
  ALNS는 시나리오별 동일한 거리 전용 Beam(B=2) 초기 해, 200반복, cost 상한20000,
  제거율0.3, T_m=100, T_score=0.05, 냉각0.99, segment20, 반영률0.2,
  후보 제한 없음, seed0~9 × 4모드로 총80회 실행했다. 모두200반복을 완료했다.
  실행 전 거리·경로 캐시를 비우고 그래프 준비·초기 해 생성 시간은 탐색 시간에서 제외했다.

| 시나리오·설정 | 거리(m) | 재통행(%) |
|---|---:|---:|
| 경복궁→서대문 Dijkstra / A* | 1575.246 / 1575.246 | 최단거리 검증 |
| 순환 거리 전용 Beam B2 | 3975.23 | 35.706 |
| 순환 재통행5% Beam B2 / B8 | 4194.25 | 2.167 |
| 순환 재통행5% 전수 최적 | 4098.939 | 0.656 |
| 순환 재통행5% ALNS seed0 | 4181.339 | 29.458 |
| 편도 재통행5% Beam B2 / B8 | 3084.957 | 0.633 |
| 편도 재통행5% ALNS seed0~9 모두 | 2901.572 | 0 |
| 편도 재통행5% 전수 최적 | 3032.243 | 0 |

- 최단거리: 각3회 워밍업 후30회 번갈아 측정. Dijkstra p50/p95=9.003/10.665ms,
  A* p50/p95=2.129/2.467ms. 해당 로컬 관측이며 탐색 노드 수는 계측하지 않았다.
- 순환5% 허용 범위 안 조합은146개. ALNS 10seed 재통행은 최저0.656%, 중앙값1.412%,
  최고29.458%였다. 단일 seed로 개선 성능을 확정할 수 없으며 5%가 서비스 최적값이라는 근거도 아니다.
- 제품 함수를 변경하지 않고 실제 Beam 유지 목록을 추적했다. 순환5%에서 B2는 깊이1,
  B8은 깊이2에서 전수 최적 조합으로 이어지는 접두 순서를 모두 탈락시켰다.
  B1320에서는 전수 최적과 일치했다. 중간 평가 개선의 필요성을 조사할 근거이지
  rollout 등 특정 대체 방법의 성능을 검증한 결과는 아니다.
- 새 편도 풀에는5% 허용 범위 안 조합이19개 있었다. ALNS는10seed 모두 재통행0%를 찾았지만
  거리 동점 비교까지 보면3032.243m가 더 좋아 전체 목적값의 전수 최적에는 도달하지 않았다.
- 편도 B2/7.5%는3370.353m·재통행0%로 허용 범위를 벗어났다. 중간 순위와 가지치기가 달라져,
  허용 범위를 넓힌다고 최종 결과가 항상 좋아지지는 않는다. 풀 안의 해 부재와 구분한다.
- 실제 ALNS 반환 객체에서 best 보존 검사는 모두 통과했다. 순환5%/seed3의 별도 catalog 비교에는
  덧셈 순서에 따른 약9e-13m 차이가 있어 원본값과 진단 플래그를 구분해 기록했다.
- 전체 후보 풀 성능, GRASP→ALNS 연결, API Workflow, 실제 보행 만족도는 여전히 미검증이다.

```bash
./.venv/Scripts/python.exe -m benchmarks.runner.waypoint_overlap_audit
```

중간 상태를 확인하려면 위 실행이 출력한 **실제 결과 폴더 경로**를 다음 모듈의 인자로 전달한다.

```bash
./.venv/Scripts/python.exe -m benchmarks.runner.waypoint_overlap_diagnostics tmp/waypoint_overlap_validation/run_YYYYMMDD_HHMMSS
```

위 날짜 자리표시는 생성된 폴더명으로 바꾼다. 실행기는 기존 산출물을 덮어쓰지 않는다.

## Engine 반환 계약

(2026-09-19 갱신) 8축→2축 축소와 함께 `CircularBeamEngine`·`OnewayBeamEngine`·`CircularGraspEngine`·
`OnewayGraspEngine`·`CircularAlnsEngine`·`OnewayAlnsEngine`·`CircularRcspEngine`·`OnewayRcspEngine`·
`OnewayPlateauEngine`·`OnewayBidirectionalAstarEngine`·`OnewayBidirectionalDijkstraEngine` 11개
엔진이 전부 삭제됐다. `src/route_engine/engines/__init__.py`가 내보내는 엔진은 이제
`GpsArtEngine`·`OnewayAstarEngine`·`WaypointComposerEngine` 3개뿐이다. 4번째 서비스 엔진
`CircularGraspWaypointAlnsEngine`(`circular_grasp_waypoint_alns.py`)은 순환 임포트를 피하려고
`__init__.py`에는 두지 않고 `route_service.py`가 직접 import한다. `OnewayDijkstraEngine`
(`dijkstra.py`)은 삭제되지 않았지만 이전과 마찬가지로 production 경로 어디서도 쓰이지
않는 죽은 코드로 남아 있다(`benchmarks/solvers/dijkstra_solver.py` 전용).

`route_service.py::RouteService.base_engines`는 현재 다음과 같다:

```python
self.base_engines: dict = {
    WalkMode.CIRCULAR_RANDOM: CircularGraspWaypointAlnsEngine,
    WalkMode.ONEWAY_SHORTEST: OnewayAstarEngine,
    WalkMode.ONEWAY_RANDOM:   OnewayAstarEngine,
    WalkMode.GPS_ART:         GpsArtEngine,
    WalkMode.WAYPOINT:        WaypointComposerEngine,
}
```

`CIRCULAR_RANDOM`은 `WaypointEngine`을 `construction="grasp", refinement="alns"`로 고정한
`CircularGraspWaypointAlnsEngine`을 쓴다. `mode`는 여전히 `"distance"` 고정이지만(2026-09-19,
#462에서 `_CostCache.cost_context`로 배선) `route_service.py`가 `_build_cost_context(preference)`로
만든 `WeightedEdgeCost`를 엔진 생성자에 넘기면 GRASP 구축 반복과 ALNS 최종 재연결의
A*(`BuildCycleRoute`)가 그 가중 비용으로 구간을 잇는다 — 단, ALNS 자체의 경유지 선택
(`alns_search`, destroy-repair)은 `WaypointPoolResult.distance()`(순수 거리)만 보므로 어떤 노드를
경유지로 쓸지·몇 번째로 방문할지는 여전히 거리 기준이다. `ONEWAY_RANDOM`은 지금은
`ONEWAY_SHORTEST`와 완전히 같은 `OnewayAstarEngine`을 쓴다(우회 로직이 아직 없는 임시 상태) —
다만 나중에 갈라칠 수 있도록 `_build_engine()`에서 `ONEWAY_SHORTEST`와 분기를 합치지 않고
별도 `if`로 남겨 뒀다. `oneway_random`은 여전히 안전·편안 가중치가 걸리지 않는 거리 전용
비용으로 탐색한다 — 예전 Beam 계열이 하던, "안전·자연 등을 블렌딩한 스칼라 비용으로 고른
대표 1개 + 벡터로 다양화한 나머지"라는 다양화 메커니즘(`select_diverse_paths` 직접 호출)은
`circular_random`·`oneway_random` 어느 쪽에서도 더 이상 쓰이지 않는다(그 메커니즘 자체는
`WaypointComposerEngine`의 leg 조합에만 남아 있다 — 아래 "후보 다양화" 절 참고). **반환 후보
개수는 별개다** — `oneway_random`(`OnewayAstarEngine`)은 항상 1개뿐이지만, `circular_random`
(`CircularGraspWaypointAlnsEngine`)은 아래 `WaypointEngine`의 `grasp+alns` 다중 후보 규칙을
그대로 물려받아 여전히 3개를 반환한다 — 자세한 내용은 바로 아래 문단 참고.

- `src/route_engine/engines/`의 남은 엔진(`OnewayAstarEngine`·`GpsArtEngine`·
  `WaypointComposerEngine`, 그리고 route_service가 직접 잡는 `CircularGraspWaypointAlnsEngine`)의
  `run()`은 모두 `List[WalkRouteResponse]`를 반환한다(2026-08-23 통일된 계약, 삭제된 엔진들도
  삭제 전까지는 이 계약을 따랐다).
- `oneway_astar`의 `find_path()`는 노드ID 경로 후보를 `list[list[int]]`로 감싸서 반환한다.
  `gps_art`·`waypoint`는 자체 `find_path()`가 없다 — 대신 다른 엔진들의 `run()` 결과를
  조합(`WaypointComposerEngine`)하거나 그 조합에 위임(`GpsArtEngine`)해서 최종 경로를 만든다.
- 경유지 선택 계열(`waypoint_engine_assembly.py::WaypointEngine`과 그 얇은 래퍼 5종 —
  `circular_grasp_waypoint_{alns,local,vnd,vns}.py`·`circular_beam_waypoint_vns.py`)의 `run()`도
  같은 계약(`list[WalkRouteResponse]`)이며, 2026-09-17부터 `MULTI_CANDIDATE_COMBOS`에 속한
  조합에서만 **최종 경로 1개 + 후보 2개**, 합계 `CANDIDATE_COUNT`(=3)개를 반환한다. 현재 그
  집합은 `grasp+local`·`grasp+alns` 둘이고, 나머지 조합(`grasp+vnd`·`grasp+vns`·`beam+*`)과
  실패 상태(`NO_PATH`·`NO_NEAREST_START_NODE`)는 1개만 반환한다. `CircularGraspWaypointAlnsEngine`은
  `(construction, refinement)`을 오버라이드하지 않는 `("grasp", "alns")` 고정 래퍼이므로 이
  `grasp+alns` 규칙을 그대로 물려받는다 — `route_service.py`를 통한 `circular_random` 요청도
  실제로 후보 3개를 반환한다(2026-09-19, 실제 엔진으로 재확인). 단 `select_diverse_paths`
  기반 벡터 다양화는 쓰지 않는다(`mode="distance"` 전용) — 후보 3개는 순수하게 구축·정제
  반복이 만들어낸 서로 다른 경로들이다.
- 조합을 가른 근거는 실측이다(2026-09-17, seed 42, 벤치 fixture 160,328노드/223,927엣지, `target_km=3.0`·N=2에서 정제 후 서로 다른 경로 수): `grasp+alns` 18~21개, `grasp+local` 2~8개, `grasp+vnd` 1~2개, `grasp+vns` 2~7개, `beam+*` 1개. VND·VNS는 결정적 단조 하강이라 서로 다른 구축 결과 24개가 같은 지역 최적해로 수렴하고, `beam_construction()`은 애초에 `ConstructionResult`를 1개만 yield한다. 재현 기준은 구축×정제 루프를 그대로 돌면서 매 반복의 `Route`를 모아 `node_ids` 기준 중복을 제거하는 것이다.
- `WaypointEngine.find_path()`는 위 조합에서도 **최종 경로 노드열 하나**(`list[int]`)만 반환한다 — `circular_beam`·`oneway_beam`·`oneway_astar`가 `list[list[int]]`를 반환하는 것과 다르다. 후보는 `last_alternative_routes` 속성으로만 나간다. 그래서 이 함수를 쓰는 벤치마크 어댑터(`benchmarks/solvers/_circular_engine_common.py::run_circular_engine_distance_only`)와 CSV 지표는 이 변경으로 바뀌지 않는다. `benchmarks/results.py`의 `route_distance_km()`이 `paths` 전체를 합산하므로, 후보를 `paths`에 넣었다면 거리·게이트 지표가 전부 어긋났을 것이다.
- 후보 선별은 `evaluate_route`/`better`의 사전식 키(`RouteObjective.sort_key()`)로 **안정 정렬**한 뒤 `node_ids` 완전 일치 중복만 제거하고, 그래도 2개를 못 채우면 최종 경로를 복제해 채운다. 최선해 추적(`better` 순차 갱신)은 그대로 두고 후보 수집만 옆에 붙였으므로, 같은 seed에서 최종 경로는 이 변경 전과 동일하다(실측 9조건에서 `|cost - target_m|`이 소수점까지 일치, 2026-09-17).
- 복제 발동률은 실측 5.0%다(2026-09-17, `grasp+local`, 출발지 8 × 거리 5종 × N=2 × seed {42, 7, 123} = 120회 중 6회). 발동 조건은 남산 1km·북한산 3km 둘뿐이고 세 시드에서 모두 같은 조건에서만 걸렸다 — 무작위 변동이 아니라 성긴 도로망 + 짧은 목표거리의 구조적 한계다. 복제는 매번 1개였고(후보 2개를 모두 복제한 경우 0회), dense·medium 60회와 5km 이상 72회에서는 한 번도 발동하지 않았다. N=3·4는 별도 16조건에서 서로 다른 경로가 최소 5개였다(seed 42).
- `oneway_shortest` 모드의 실제 사용 엔진은 `dijkstra.py`(`OnewayDijkstraEngine`)에서 `oneway_astar.py`(`OnewayAstarEngine`)로 교체되었다. 배경·현재 사용처는 바로 아래 "oneway_shortest 엔진: 거리 전용(distance-only) weight + Haversine 휴리스틱" 절 참고.
- `route_service.get_route()`도 같은 계약(`List[WalkRouteResponse]`)으로 반환한다. POI 조회는 성공한 후보 전부에 적용하고, `RouteHistory` 저장은 아직 대표 후보(리스트의 첫 번째)만 한다 — 사용자가 실제로 어떤 후보를 골랐는지 아직 API로 전달받지 않기 때문이며, 그 흐름이 생기면 선택된 후보를 저장하도록 바꿀 예정이다(`route_service.py`의 `TODO` 주석 참고). 리스트 전체는 그대로 반환한다.
- `OnewayAstarEngine._heuristic`은 2026-08-23부터 랜드마크 기반 ALT 방식이 아니라 Haversine 직선거리(`PathUtils._haversine_m`)를 쓴다. 이에 따라 `precompute_landmarks()`/`_select_landmarks()`/`landmark_dist` 노드 속성은 코드에서 전부 제거됐다 — 상세는 아래 "oneway_shortest 엔진: 거리 전용(distance-only) weight + Haversine 휴리스틱" 절 참고.

## 후보 다양화(벡터 score 기반)

**왜 필요한가**

(2026-09-19 갱신) 원래 이 다양화는 beam search(`oneway_beam.py`/`circular_beam.py`, 둘 다
삭제됨)를 위해 만들었다 — 내부적으로 여러 후보(`_BEAM_WIDTH=8`)를 유지하다가도 최종적으로는
안전·자연·평지 등을 전부 하나의 스칼라(`custom_score`)로 블렌딩한 기준 하나로만 후보를
좁혀서, 여러 개를 뽑아도 사실상 비슷한 경로만 나오는 문제가 있었다. 이 절의 "벡터 score"·
"경로별 벡터 합산과 다양화 선택" 메커니즘 자체는 지금도 쓰인다 — 다만 소비처가 Beam
엔진에서 `WaypointComposerEngine`의 leg 조합(아래 "`waypoint.py`" 절)으로 좁혀졌다.
`circular_random`·`oneway_random`은 더 이상 이 메커니즘을 쓰지 않는다(위 "Engine 반환 계약"
절 참고 — 지금은 각각 `CircularGraspWaypointAlnsEngine`/`OnewayAstarEngine`을 쓰고, 후보가
여럿이어도 그 개수는 이 벡터 다양화가 아니라 `WaypointEngine`의 grasp+alns 다중 후보 규칙이
정한다).
- `target_km`(거리 허용오차) 자체는 이 다양화와 무관하게 여전히 1순위 조건이다 — 벡터 비교는 목표 거리를 만족(또는 가장 근접)하는 후보 풀 안에서만 적용한다.

**벡터 score — `scoring_engine.py`**

- (2026-09-19 갱신) `compute_score_vector(graph) -> {(u, v): {"safety": cost, "comfort": cost}, ...}` —
  8축→2축 축소로 이제 2차원이다(`nature`/`convenience`/`accessibility` 등은 삭제됐다).
  `FEATURE_DIMENSIONS = ("safety", "comfort")`를 그대로 순회해 만든다. 이 값을 만들 때 쓰던
  `calculate_custom_score`/`compute_custom_score_lookup`(안전·자연 등을 블렌딩한 할인 모델)은
  이번 축소로 완전히 삭제됐다 — 지금은 이 함수를 부르는 유일한 소비처가
  `WaypointComposerEngine`(아래 참고)이며, "profile의 가중 스칼라로 대표 후보를 뽑는다"는
  개념 자체가 없다(profile이 삭제됐다).
- 각 차원 값은 `length * (1 - feature)`다. `feature`(0~1, 1이 가장 좋음)가 1이면 0, 0이면 그 edge의 `length` 전체가 비용이 된다 — 경로를 따라 그대로 합산할 수 있고, 모든 차원이 이미 미터 단위라 추가 정규화 없이 비교 가능하다.

**경로별 벡터 합산과 다양화 선택 — `path_utils.py`**

- `PathUtils.path_score_vector(path, vector_lookup)`: 경로를 따라 벡터를 성분별로 합산한다.
- `PathUtils.vector_distance(a, b)`: 두 벡터 사이 유클리드 거리.
- `PathUtils.select_diverse_paths(candidates, k=3)`: **후보 1**(`candidates[0]`, 호출부가 기존 기준으로 이미 정한 대표)을 고정하고, 나머지 중 이미 뽑힌 것들과의 최소거리가 가장 큰 것을 greedy farthest-point(k-center) 방식으로 최대 `k-1`개 더 뽑는다. 최댓값이 아니라 **최솟값의 최댓값**을 기준으로 삼는 이유는, "다른 후보와는 멀어도 기존에 뽑힌 것 중 하나와 거의 같은" 사실상의 중복을 배제하기 위해서다. 후보가 `k`개 미만이면 있는 만큼만 반환한다. `payload` 자리에는 노드 ID 리스트뿐 아니라 `WalkRouteResponse` 등 어떤 타입도 그대로 통과시킬 수 있다(`TypeVar` 기반 제네릭).

**`waypoint.py`: leg 조합에도 다양화 전파**

- `WaypointComposerEngine`이 leg 엔진을 호출할 때 이제 그 leg의 전체 후보 리스트(`engine.run()`)와 노드열 리스트(`engine.last_path_nodes_by_candidate`)를 둘 다 보관한다. 상태 판정·재시도(`oneway_shortest`로 대체)·`visited_nodes` 누적은 기존처럼 대표 후보(인덱스 0) 기준으로만 한다.
- 모든 leg가 성공했을 때만: leg별로 같은 인덱스(0/1/2)끼리 짝지어 이어붙인 "슬롯" 최대 3개를 만든다(leg에 그 인덱스의 후보가 없으면 대표로 대체 — 예: `oneway_shortest` leg는 항상 대표만 있음). 슬롯 중 노드열이 완전히 같은 것(예: 전 leg가 `oneway_shortest`라 애초에 대안이 없는 경우)은 버리고, 남은 슬롯들의 전체 경로 벡터를 계산해 `select_diverse_paths`로 최종 정리한다.
- 이 방식은 leg 개수와 무관하게 항상 최대 3개만 계산한다 — leg별 후보를 전부 조합(3^legs)하지는 않는다. 일부 leg가 실패한 경우엔 다양화 없이 기존처럼 대표 경로 1개만 이어붙여 반환한다(부분/실패 경로까지 3개로 부풀리지 않음).
- 검증: 단일 leg(순수 `oneway_random`), 2-leg(경유지 1개, 양쪽 다 `oneway_random`, 각각 3-lane), 2-leg 전부 `oneway_shortest`(대안 없음, degenerate case) 세 시나리오를 실제 toy 그래프로 직접 실행해 각각 3개/3개/1개(중복 제거 확인)가 나오는 것까지 확인했다(2026-08-07). **정식 `tests/` 회귀 테스트로는 아직 옮기지 않았다** — 지금까지는 임시 스크립트로만 검증했다.

**`route_service.py`: POI·이력 처리**

- POI 조회(`RoutePoiRepository.find_near_route`)는 성공한 후보 전부에 적용한다.
- `RouteHistory` 저장은 아직 대표 후보(리스트의 첫 번째)만 한다 — 사용자가 실제로 어떤 후보를 선택했는지 API로 전달받는 흐름이 아직 없기 때문이다. **알려진 개선 항목**: 그 흐름이 생기면 사용자가 실제로 고른 후보를 저장하도록 바꿀 예정이다(`route_service.py`의 `TODO` 주석 참고).
- `walk_router.py`(직접 REST API)는 의도적으로 이번 변경 범위에서 제외했다 — 레거시로 간주하기로 했고, `response.status.value`가 이미 실제 반환 타입(`List[...]`)과 맞지 않는 기존 버그도 그대로 둔다.

**아직 확인 안 된 것**: 실제 그래프 규모에서 이 다양화가 실제로 서로 다른 "의미 있는" 3개(예: 정말 확연히 다른 동선)를 만들어내는지는 toy 그래프 검증까지만 했고, 실서비스 규모 그래프·프런트엔드 노출까지는 확인하지 않았다. `tests/`에 정식 회귀 테스트도 아직 없다.

## 방향 전환(turn_cost) 진단 지표 (2026-09-16)

**왜 필요한가**: 순환 경로 엔진 비교에 쓰던 지표(거리 오차, 자기중첩 비율, 실행시간)에는 "이 경로가 걷기에 얼마나 편안한가"를 나타내는 축이 없었다. 회전은 도로 하나(edge)의 속성이 아니라 "직전 도로 + 교차로 + 다음 도로"의 관계에서만 정의되므로 edge에 미리 저장할 수 없고, 특정 엔진에 종속시키지 않기 위해 `PathUtils`에 엔진 독립 함수로 구현했다. **엔진의 accept/reject 기준이나 목적함수에는 아직 연결하지 않았다** — 진단·비교 전용이다.

**핵심 함수 — `path_utils.py`**

- `latlon_to_local_xy(lat, lon, *, lat_ref)`: 노드 위경도를 `lat_ref` 위도 기준 로컬 평면(등장방형 근사)으로 투영한다. 도보 edge 스케일(수십~수백 m)을 전제하며, 원시 위경도를 직접 벡터 계산에 쓰지 않기 위한 투영 단계다.
- `turn_angle(prev_xy, curr_xy, next_xy) -> float | None`: 평면 좌표 3점의 회전각(도, 0~180, 좌우 미구분). 직전==현재 또는 현재==다음(길이 0 벡터)이면 `None`.
- `turn_angle_at(G, prev_node, curr_node, next_node) -> float | None`: 위 두 함수를 그래프 노드에 적용하는 래퍼. 그래프 좌표 상태에 의존하므로 `turn_angle`과 달리 엄밀한 순수 함수는 아니다.
- `PathUtils.path_distance_m(path, *, closed=False) -> float`: 닫힌 경로는 시작 노드 중복 여부와 무관하게 이음매 구간 거리를 정확히 1회만 포함한다(`_normalized_nodes`로 정규화).
- `PathUtils.turn_angle_result(path, *, closed=False) -> TurnAngleResult`: 회전각 목록(`angles_deg`)과 정의 불가 원인별 집계(`undefined_reasons`)를 반환한다. 닫힌 경로는 전체 노드를 모듈러 인덱스로 순회해 n개 노드 모두의 회전을 계산한다 — "메인 구간 + 이음매 패치 1개" 방식은 n-1개만 계산하는 버그가 있었다(회귀 테스트로 고정, `tests/unit/test_path_utils.py::TestTurnAngleResult`).
- `PathUtils.turn_angles(path, *, closed=False) -> list[float]`: `turn_angle_result`의 각도 목록만 반환하는 편의 함수.
- `PathUtils.turn_metrics(path, *, closed=False) -> TurnMetrics`: `total_turn_deg`/`max_turn_deg`/`turn_deg_per_km`/`candidate_turn_count`/`defined_turn_count`/`undefined_turn_count`/`undefined_turn_reasons`를 담은 통계.
- `count_turns_at_or_above(angles_deg, threshold_deg) -> int`: 특정 임계값 이상 회전 개수. 45°/60°/90° 등은 검증된 인간공학적 기준이 아니라 잠정 운영 임계값이므로 `TurnMetrics`에 필드로 고정하지 않고, 필요할 때 이 함수로 동적 계산한다.

**실측 검증**: 서울 도보 그래프·당시 활성 순환 엔진 9종(`grasp-wp-*`, `beam-wp-*`)·시나리오 25개 전수(225회) 기준 정의 불가 회전 0건, 거리당 회전량 740.7~845.4°/km. 지표 간(누적 회전량 vs 급회전 패턴) 순위 불일치, 일부 엔진(`grasp-wp-alns`/`beam-wp-alns`/`beam-wp-vns`)의 seed 의존성, 임계값별 순위 민감도 등 세부 결과는 [analysis/turn_cost/](../../analysis/turn_cost/)(탐색적 분석, 확정 결론 아님) 참고. (2026-09-19 갱신) `beam-wp-*` 계열은 8축→2축 축소로 이후 전부 삭제됐다 — 이 실측은 그 이전 시점의 관측이며 현재 코드로는 재현할 수 없다. 현재 활성 순환 엔진은 서비스용 `CircularGraspWaypointAlnsEngine`(=`grasp-wp-alns`) 하나뿐이고, 나머지 `grasp-wp-*`(local/vnd/vns)는 여전히 벤치마크·시각화 전용으로 존재한다.

**아직 확인 안 된 것**: 45°/60°/90° 등 후보 임계값이 실제 보행 속도·주관적 불편도와 상관관계가 있는지는 사용자 행동 데이터가 없어 검증하지 못했다. 순환 엔진이 최종 확정된 뒤 이 지표를 목적함수에 연결할지도 아직 판단하지 않았다.

## oneway_shortest 엔진: 거리 전용(distance-only) weight + Haversine 휴리스틱

**무엇이 바뀌었나(2026-08-23)**

- `OnewayDijkstraEngine`(`dijkstra.py`)·`OnewayAstarEngine`(`oneway_astar.py`) 두 엔진 모두 weight 계산이 `scoring_engine.py`의 `compute_distance_only_lookup(graph)`로 바뀌었다(또는 처음부터 이걸로 신설됐다). 기존 `compute_custom_score_lookup`(안전·자연·평지 등을 블렌딩한 `custom_score`) 대신 **거리(length)만** weight로 쓴다. `bonus`/`slope_penalty`/`caution_penalty`/`comfort_penalty`는 전혀 반영하지 않는다. (2026-09-19 갱신) `blocked_tags`에 의한 edge 차단은 `profiles.py` 삭제와 함께 이제 코드 자체에 없다 — `compute_distance_only_lookup`/`_make_distance_weight` 모두 `blocked_tags` 인자를 받지 않는다.
- `OnewayAstarEngine._heuristic`은 랜드마크 기반 ALT 방식 대신 **Haversine 직선거리**(`PathUtils._haversine_m`)를 쓴다. weight가 거리(length) 그대로이므로 직선거리 ≤ 실제 도로망 거리(삼각부등식)가 항상 성립해 별도 보정(`min_ratio`) 없이 admissible하다.
- **(2026-09-12 갱신) 휴리스틱이 다시 선택 가능해졌다.** `OnewayAstarEngine`은 이제 다음 순서로 쓸 휴리스틱을 고른다 — ① 생성자에 명시해서 넘긴 `heuristic` 인자 → ② 그래프에 부착된 ALT(`G.graph["alt_heuristic"]`, 기동 때 `alt_runtime.prepare_alt_heuristic()`이 만든다) → ③ 위의 Haversine(`self._heuristic`). 셋 다 admissible해서 최적 비용은 같고 탐색 속도만 달라진다. 설정 키는 `WALK_ALT_ENABLED`(기본 `true`) · `WALK_ALT_METHOD`(기본 `planar`) · `WALK_ALT_K`(기본 `8`) · `WALK_ALT_SEED`(기본 `0`)이며, 준비에 실패하면 자동으로 ③으로 폴백한다. 되돌리려면 `WALK_ALT_ENABLED=false`로 재기동한다. 자세한 계약은 아래 "ALT 서비스 연결 (2026-09-12)" 절 참고.
- (2026-09-19 갱신) `OnewayBidirectionalAstarEngine`(`oneway_bi_astar.py`)·`OnewayBidirectionalDijkstraEngine`(`oneway_bi_dijkstra.py`)는 8축→2축 축소에서 함께 삭제됐다 — 아래 두 문단이 설명하던 "`find_path()`만 양방향 탐색으로 교체" 구조는 더 이상 존재하지 않는다.
- `precompute_landmarks()`/`_select_landmarks()`/`landmark_dist` 노드 속성은 코드에서 전부 제거됐다(`oneway_astar.py`, `dependencies.py`의 `init_route_service()`, `benchmarks/benchmark.py`, `benchmarks/run_all_scenarios.py`).
- 설계 배경·검토한 대안(전부 weight 0 vs weight를 length로 완전 대체 vs 채택된 절충안), 양방향 Dijkstra 신설 경위는 [route_engine 최단 경로 가중치 거리 전용 전환 제안](../proposals/route_engine_shortest_weight_distance_only_proposal.md) 참고 — 신설됐던 `OnewayBidirectionalDijkstraEngine` 자체는 이후 삭제됐다.

**(2026-09-17 갱신) `OnewayAstarEngine`은 더 이상 `compute_distance_only_lookup`을 호출하지 않는다**

- `run()`마다 2*E 크기 lookup dict를 새로 만들던 것을 `_make_distance_weight()`가 만드는 콜러블로 바꿨다. A*가 실제로 확인한 edge에서 바로 읽으며, 누락 `length`는 1.0, 1m 미만은 1.0으로 올림, **기존 lookup과 값이 같다**(실측 2026-09-17, artifact 엣지 223,693개 전부 일치, 차이 0건).
- 같은 실측에서 재생성 비용은 feature cache가 준비된 상태에서도 0.68~0.77초였고 변경 후 약 10μs다. `WaypointComposerEngine`은 leg마다 엔진을 새로 만들므로 leg 수만큼 반복되던 비용이다.
- `path_cost()`는 **항상 거리**를 돌려준다(벤치마크가 엔진끼리 비교하는 기준). 탐색에 쓴 비용 합이 필요하면 `weighted_path_cost()`를 쓴다.
- (2026-09-19 갱신) 나머지 한 엔진(`dijkstra.py`)은 아직 `compute_distance_only_lookup`을 쓴다 — `oneway_bi_astar.py`/`oneway_bi_dijkstra.py`는 삭제됐다.

## 안전·편안 가중 비용 (#445, 2026-09-17)

**비용식과 ALT 재사용 근거**

```
cost       = length × (1 + α × unsafe + β × discomfort)
unsafe     = λ × (1 - safety_score) + (1 - λ) × accident_score
discomfort = 1 - slope_score
```

- `scoring/scoring_engine.py::WeightedEdgeCost`(2026-09-19 갱신 — `scoring/weighted_edge_cost.py`는 삭제되고 `scoring_engine.py`에 합쳐졌다. `SCORE_ATTRS`·`SAFETY_ATTR`/`ACCIDENT_ATTR`/`SLOPE_ATTR`·`CoverageReport`·`normalize_preference_weights`도 전부 같은 파일에 있다). `custom_score`가 비용을 `length` 아래로 내릴 수 있는 **할인 모델**인 것과 달리 **페널티 전용 모델**이라 항상 `cost >= length`가 성립한다.
- 그래서 기동 때 `length`로 준비한 ALT Planar 거리표를 **사용자 가중치가 바뀌어도 다시 만들지 않고** admissible heuristic으로 그대로 쓴다. 이 불변식이 이 모듈의 존재 이유이므로 수식을 바꿀 때 가장 먼저 확인한다(`tests/unit/test_weighted_edge_cost.py::test_weight_is_never_below_length`).
- `visited_nodes` 재방문 페널티(배수 >= 1)는 가중 비용 **위에** 곱해지므로 admissibility가 유지된다.

**선호도와 비용 계수의 분리**

- `Weights.safety` / `Weights.comfort`(0~1 선호 강도, 2026-09-19 갱신 — 필드명이 `slope`가 아니라 `comfort`다)를 그대로 α·β로 쓰지 않는다. 선호도는 "얼마나 원하는가", α·β는 "탐색 비용을 몇 배까지 올릴 것인가"로 의미가 다르다.
- `normalize_preference_weights(safety, slope, weight_limit)`가 상대 비율을 지키며 `α+β <= k`로 비례 축소한다. 가중치 산출 로직(#444/#448)이 바뀌어도 비용 수식이 흔들리지 않게 하기 위한 분리다.

**적용 범위 (설계 결정 A)**

| 모드 | 비용 |
|---|---|
| `waypoint`의 `oneway_preferred` leg | 가중 |
| `waypoint`의 `oneway_shortest` leg | 새 선호 가중치 미적용. 기존 재방문 페널티는 유지 |
| `oneway_shortest` | 거리 기준 최단 유지 |
| `gps_art` | 새 선호 가중치 미적용. 기존 경유지 연결 방식 유지 |
| `oneway_random` | `custom_score`가 아니라 **거리 전용**. `OnewayAstarEngine`(=`oneway_shortest`와 동일, 임시 상태)을 쓰고, 안전·편안 가중 로직이 아직 없다 |
| `circular_random` | (2026-09-19 갱신, #462) **가중** — `CircularGraspWaypointAlnsEngine`(`mode="distance"` 고정)이 `cost_context`를 받아 GRASP 구축·ALNS 최종 재연결의 A*(`BuildCycleRoute`)에 쓴다. ALNS의 경유지 선택 자체(`alns_search`)는 거리 기준 그대로다 |

(2026-09-19 갱신, #467) #462는 `cost_context`가 A* 구간 연결 비용에만 영향을 줬고, 후보들 중 **어느 것을 채택할지**(`RouteObjective.sort_key()`/`evaluate_route`)는 여전히 거리·재통행 비율만 봤다 — 가중치를 켜도 "더 안전한 경로"가 "더 안전하지 않지만 거리가 더 정확한 경로"에 밀릴 수 있었다. `Route.weighted_cost_m`(`build_cycle_route`가 `cost_context`로 함께 합산)과 `RouteObjective.preference_penalty_ratio`(`= weighted_cost_m/distance_m - 1`, 범위 `[0, k]`)를 추가해 최종 채택·후보 선별(`_collect_alternatives`, #443)까지 선호도를 반영하도록 확장했다. `sort_key()`는 `feasible=True`일 때 `(0, repeated_edge_ratio, preference_penalty_ratio, distance_error_m)`, `feasible=False`일 때 `(1, distance_error_m, repeated_edge_ratio, preference_penalty_ratio)`다 — 두 경우 모두 왕복 퇴화 방지(`repeated_edge_ratio`)가 선호도보다 우선한다. `cost_context`가 없거나 비활성이면 `weighted_cost_m == distance_m`이라 `preference_penalty_ratio`는 항상 0.0이므로 가중치 미적용 모드의 기존 선택 결과는 바뀌지 않는다.

`waypoint`의 `oneway_random` leg가 섞인 요청은 이번 새 가중 연결 대상에서 제외한다. 자동으로
채운 구간과 명시된 `oneway_preferred` 모두 같은 규칙을 따른다. (2026-09-19 갱신) 아래 "leg
방식 결정" 표의 사유 문자열 `beam_leg_present`는 이 규칙이 처음 생겼을 때 그 leg가 실제로
`OnewayBeamEngine`이었던 이름을 그대로 쓴다 — Beam 엔진은 이후 삭제됐지만 API 응답 계약
(`preference_skipped_reason`)을 깨지 않으려고 문자열 이름은 바꾸지 않았다. `oneway_random`의
목표 거리와 기존 `custom_weights`는 유지한다.

**설문 기본값과 대화 선호 전달 (`Weights`)**

설문은 사용자 기본 선호이며, 이번 대화에서 나온 요구를 기존 `_build_weights`의
혼합 로직으로 반영한다. 기본 안전·편안 값 `0.5`도 유효한 선호다. 사용자가 이번에
언급하지 않았다는 이유로 해당 축을 0으로 바꾸지 않는다.

```
RouteExecutor -> RouteTool -> RouteService -> WaypointComposerEngine / CircularGraspWaypointAlnsEngine
```

(2026-09-19 갱신) 별도 `SafetyComfortPreference` 타입이나 `_build_preference_signal()`
변환 단계는 없다 — 둘 다 삭제됐다. `RouteExecutor._build_weights()`가 만든 `Weights`
객체를 `waypoint_route` tool 호출 시 `args["preference"]`로 **그대로 재사용**한다.
순환 요청은 `RouteExecutor`가 전달한 `custom_weights`를 `circular_random_route`가
`RouteService.get_route(preference=custom_weights)`로도 전달한다(#471). 서비스가 이 값으로
만든 요청 비용 객체를 순환 엔진의 구간 연결과 후보 평가가 함께 사용한다. 최단 경로·
편도 우회·GPS Art tool은 서비스에 `preference`를 전달하지 않는다. 설문 기록이 없으면
`Weights()`의 기본값(`safety=0.5, comfort=0.0`)을 쓴다. 설문 조회는 요청당 한 번이며
기본값·혼합 계산식은 변경하지 않았다.
직접 서비스 호출에서 `preference`를 생략한 경우는 거리 기준이다. 직접 전달한
신호에서 생략한 축은 계수 0이며, 챗봇은 혼합 결과의 두 축을 모두 전달한다.

**순환 선호 전달 검증 (#471, 2026-09-19)**

- `tests/integration/test_circular_preference_flow.py`: 실제 `RouteExecutor`·`RouteTool`·
  `RouteService`·GRASP+ALNS를 이어 설문/대화 혼합값, 엔진 비용 객체, 완성 후보의 가중 비용을
  확인한다. 가중치 0·점수 부족·설정 비활성 시 거리 기준 처리와 최단/GPS Art의 적용 범위도
  검증한다. DB·인증과 `StructuredTool.ainvoke` 바인딩만 테스트 대역이다.
- 수정 전 같은 테스트는 엔진의 `cost_context is not None` 검증에서 실패했다.
- 실그래프 재현: 저장소 루트에서 `python -m tests.integration.check_circular_preference_artifact`.
  `.env`의 `WALK_GRAPH_SOURCE=artifact`, `WALK_GRAPH_ARTIFACT_PATH=artifacts/walk_graph_v1.pkl`,
  `WALK_GRAPH_DATA_VERSION=v3-2026-09-19`가 필요하다. 테스트 프로세스 안에서 실제 앱 lifespan을
  실행하고 `POST /api/prewalk/intent`를 호출한다. LangGraph·StructuredTool·ALT·순환 엔진은 실제
  구현이며, DB 초기화·인증·저장소·확인 발화 판정은 대체한다. 외부 LLM·DB·Valkey 연동 검증은 아니다.
- 2026-09-19 Windows 로컬, Python 3.12.14 / NetworkX 3.6, [v3 그래프](graph_contract.md)의
  노드 160,197개·간선 223,693개로 실행했다. 출발 좌표 `(37.5759, 126.9768)`, 목표 3km,
  엔진 기본 시드 42에서 아래 세 요청 모두 성공했고 각각 후보 3개와 비용 합계를 확인했다.
  최종 후보의 관측값이며 고정 기대값이나 전체 품질·성능 평가가 아니다.

| 요청 | 비용 계수 α / β | 실제 거리(m) | 위험 페널티 평균 | 불편 페널티 평균 | 재통행 비율 | 요청 시간(s) |
|---|---|---|---|---|---|---|
| 거리 기준(선호 0 / 0) | 0 / 0 | 2992.534 | 0.305508 | 0.098065 | 0.013186 | 9.81 |
| 안전 요구 추가 | 0.296954 / 0.203046 | 2925.390 | 0.346635 | 0.001148 | 0 | 9.93 |
| 편안 요구 추가 | 0.118343 / 0.381657 | 2981.180 | 0.294899 | 0.009204 | 0.013237 | 8.95 |

안전/편안 요청은 기본 선호 `(0.2, 0.4)`에 해당 축의 `high`·`explicit_soft` 라벨을
반영했다. 각각 최종 선호는 `(0.585, 0.4)`, `(0.2, 0.645)`다. 위험·불편은 거리로 가중한
평균이며 낮을수록 좋다. 안전 요구 사례도 편안 기본값과 재통행 우선순위가 함께 작동하므로
개별 위험 지표가 거리 기준보다 반드시 낮아지지는 않았다. 이번 검증은 선호 전달과 비용 적용의
근거이며, 개별 지표의 단조 개선이나 품질 수용 여부를 확정하지 않는다.

**leg 방식 결정 (패딩 전)**

| 요청 | 채우는 방식 | 사유 |
|---|---|---|
| `oneway_random`이 섞임 | `oneway_shortest` | `beam_leg_present` |
| 미지정 + 선호 신호 없음(직접 호출) | `oneway_shortest` | `no_preference` |
| 미지정 + 두 축 모두 0 | `oneway_shortest` | `zero_weights` |
| 미지정 + 선호 있음 + 점수 없음 | `oneway_shortest` | `scores_unavailable` |
| 미지정 + 선호 있음 + 점수 있음 | `oneway_preferred` | — |

자동 패딩 **전에** 판단한다. 먼저 `oneway_shortest`로 채워 버리면 "사용자가 고른
최단"과 "서비스가 채운 연결"을 더 이상 구분할 수 없다. 명시적으로 고른 구간은
저장된 선호가 있어도 바꾸지 않는다.

leg 실패 시의 대체 경로는 **가중치도 재방문 페널티도 걸지 않는** 순수 거리 기준이다.
앞선 시도가 이미 실패했는데 제약을 남겨 두면 대체까지 같은 이유로 실패할 수 있다.
선호 구간 중 하나라도 거리 기준으로 대체되면 `preference_applied=False`,
`preference_skipped_reason=preferred_search_failed`를 반환한다. 성공한 다른 구간의
선호 경로는 유지하되, 전체 요청의 선호 적용 완료라고 표시하지 않는다.

**기동 준비와 요청 격리**

- 점수 적재 상태 검사(`check_coverage`, O(E), 실측 0.28~0.30초)는 **기동 때 1회**만 돌려 `G.graph["weighted_cost_coverage"]`에 붙인다(`weighted_cost_runtime.py`, `alt_runtime.py`와 같은 prepare → attach → get 구조).
- 요청은 붙어 있는 적재율·중앙값만 읽어 자기 α·β로 객체를 만든다 — 실측 1000회 0.5ms(요청당 약 0.5μs), 그래프 순회 없음.
- 그래프에 붙는 것은 **사용자와 무관한 데이터**뿐이다. α·β는 붙이지 않는다. 요청당 하나 만들어 그 요청의 모든 구간이 공유한다.

**결측 처리**

- 세 점수 컬럼은 nullable이고 server default가 없다. NULL은 "미계산", `0.0`은 "계산했고 0"이다.
- 결측을 엣지 단위로 `0`으로 대체하지 않는다 — 그러면 점수가 없는 도로가 가장 안전한 도로로 읽혀 안전 가중치를 올릴수록 데이터 없는 길로 몰린다.
- 그래프 단위 커버리지 게이트가 판정하고(`WALK_SCORE_COVERAGE_MIN`, 기본 `0.95`), 통과한 뒤 남은 NULL만 중앙값으로 대체하며 횟수를 센다.
- 점수가 `0~1`을 벗어나면 clamp하지 않고 엣지 정보를 담아 예외를 던진다.

**우회 상한은 실험용으로 보존, 일반 요청에는 미적용**

일반 요청은 길다는 이유로 선호 경로를 최단 경로로 강제 대체하지 않는다. 우회 상한용
기준 경로 탐색도 수행하지 않는다. 이전 운영 설정 `WALK_DETOUR_MAX_RATIO`는 제거했으며,
환경변수에 남아 있더라도 이 정책을 활성화하지 않는다.

`scoring/detour_cap.py`와 Composer의 기준 경로·대체 구현, 관련 테스트는 보존했다.
`experimental_detour_max_ratio`를 직접 명시한 실험만 해당 정책을 실행한다(기본 `None`).
RouteService와 API는 이 인자를 전달하지 않는다. 필요성·비율·초과 시 처리·Beam 혼합은
[우회 정책 검토안](../proposals/route_engine_detour_policy_proposal.md)에서 팀이 논의한다.
현재 구현 위치와 재현 방법도 이 문서에 있다.

**응답 필드**

| 필드 | 의미 |
|---|---|
| `preference_applied` | 요청한 새 가중 연결이 전체 경로에 적용됐는가. 일부 거리 대체나 부분 경로면 `False` |
| `preference_skipped_reason` | 반영하지 못한 사유 |

일반 요청의 사유 값은 `no_preference`, `zero_weights`, `beam_leg_present`,
`scores_unavailable`, `preferred_search_failed`, `partial_route`다.
`detour_cap_exceeded`, `baseline_failed`는 보존한 실험에서만 사용한다.
실험의 `baseline_failed`는 선호 경로를 유지하지만 상한을 검증하지 못했다는 뜻으로,
`preference_applied=True`와 함께 반환될 수 있다.

**설정과 복구**

| 키 | 기본값 | 의미 |
|---|---|---|
| `WALK_WEIGHTED_COST_ENABLED` | `true` | (2026-09-19 갱신) `false`면 새 가중 연결을 끈다(`oneway_preferred` leg도 순수 거리로 처리) |
| `WALK_WEIGHT_LIMIT` | `0.7` | (2026-09-20 갱신) `α+β` 상한(k) |
| `WALK_UNSAFE_ACCIDENT_RATIO` | `0.5` | `unsafe` 결합 비율(λ) |
| `WALK_SCORE_COVERAGE_MIN` | `0.95` | 게이트 통과 기준 |

준비 실패·커버리지 미달·설정 비활성 시 새 가중 연결은 거리 기준으로 처리하고 기동을
막지 않는다. 재방문 페널티는 이 설정으로 비활성화되지 않는다.

**현재 확인 상태 (2026-09-19, 로컬 v3 artifact)**

2026-09-17의 이전 artifact는 세 점수 적재율이 `0.0`이어서 게이트가 가중 모드를 껐다.
2026-09-19 로컬에서 `v3-2026-09-19`를 실제 앱 기동 경로로 로드했을 때는 세 점수가 모두
100%였고 게이트를 통과했다. 파일·환경별 관측이므로 운영 배포 상태를 뜻하지 않는다.
데이터 버전·재현 위치는 [graph_contract.md](graph_contract.md) 참고.

`λ`(`WALK_UNSAFE_ACCIDENT_RATIO`)는 안전시설 부족과 사고위험의 결합 비율로 서비스 의미에 해당한다. 데이터팀이 결합된 단일 점수를 제공하기로 하면 이 설정은 사라진다. 알고리즘 코드에는 기본값을 두지 않고 설정으로만 주입한다.

**Haversine 휴리스틱의 admissibility 전제 — 새 테스트 그래프를 만들 때 주의**

- Haversine 휴리스틱이 admissible하려면 **모든 edge의 declared `length`가 그 edge 양 끝 노드의 실제 좌표 간 직선거리 이상**이어야 한다(직선이 두 점 사이 최단 경로이므로, 도로가 직선보다 짧을 수는 없다는 물리적 전제). 실제 production 그래프(OSM/Kakao 도로망)는 이 전제를 자연스럽게 만족할 것으로 예상하지만 실측 확인은 안 했다.
- 좌표와 `length`를 서로 무관하게 임의로 정하는 합성 테스트 그래프(toy graph)는 이 전제를 쉽게 어길 수 있다 — 실제로 `tests/unit/test_visited_nodes_penalty.py`의 `diamond_graph` fixture가 이 문제로 `OnewayAstarEngine`이 더 긴 경로를 반환하는 회귀를 냈다가 수정됐다(2026-08-23, 좌표를 모든 length보다 훨씬 작은 범위로 재조정). 새 toy graph를 만들 때는 노드 좌표 차이를 declared length보다 충분히 작게 잡아 이 문제를 피해야 한다.

**이전 방식(A*(ALT))과의 차이 — 왜 바뀌었나**

- 이전에는 A*가 `custom_score`(profile 가중치가 걸린 비용)를 최소화했고, 휴리스틱도 그에 맞춰 랜드마크 기반 실거리 추정(`landmark_dist`)에 `min_ratio`(그래프 전체 최소 cost/length 비율) 보정을 곱해 admissible을 유지했다.
- 최단 경로류 엔진(Dijkstra/A*/양방향 A*)의 목적을 "profile 가중치와 무관하게 순수 거리 기준 최단 경로"로 좁히면서, `custom_score` 계산 자체가 필요 없어졌고 — 그에 따라 랜드마크 기반 보정도 함께 불필요해졌다. 거리(길이)와 weight가 같은 값이므로 Haversine 직선거리가 그대로 admissible 하한이 된다.
- (2026-09-19 갱신) `beam`/`grasp`/`alns`/`rcsp`/`plateau` 계열과 `circular_beam`/`circular_grasp`/`circular_alns`/`circular_rcsp`는 8축→2축 축소에서 전부 삭제됐다. `circular_random`은 지금 `CircularGraspWaypointAlnsEngine`(`mode="distance"`)을 쓴다 — `calculate_custom_score` 자체도 이 축소로 삭제됐고, 그 자리는 부활하지 않았다. 안전·편안 가중은 그 대신 `_CostCache.cost_context`(`WeightedEdgeCost`, #462)로 별도 배선됐다 — 위 "적용 범위" 표 참고.

**`OnewayDijkstraEngine`의 현재 상태 — production에서는 죽은 코드**

- (2026-09-19 갱신) `OnewayBidirectionalDijkstraEngine`은 8축→2축 축소에서 삭제됐다 — 아래는 지금 남아 있는 `OnewayDijkstraEngine`(`dijkstra.py`)만의 상태다.
- `route_service.py`·`waypoint.py`(`_LEG_ENGINES`)·`gps_art.py` 등 실제 요청을 처리하는 코드 경로 어디에서도 `OnewayDijkstraEngine`을 참조하지 않는다.
- `benchmarks/solvers/dijkstra_solver.py`(A*와 나란히 비교하기 위한 baseline)·`benchmarks/benchmark.py`의 `SOLVER_REGISTRY`·`benchmarks/run_all_scenarios.py`의 `ONEWAY_ALGOS` 목록에서만 쓰인다.
- `tests/`에는 이를 다루는 테스트가 하나도 없다 — 회귀 검증 없이 benchmark 용도로만 유지되는 상태다.
- **해결된 불일치(2026-08-23, 역사적 기록)**: `OnewayDijkstraEngine.run()`은 2026-08-06 리팩터 때 형제 엔진들이 전부 `List[WalkRouteResponse]`로 맞출 때 함께 수정되지 않아 단일 `WalkRouteResponse`를 반환했었다. 2026-08-23에 당시 GRASP/ALNS/RCSP/Plateau 계열을 포함한 8개 파일 전부를 `List[WalkRouteResponse]`로 통일했다 — 그 8개 파일은 이후(8축→2축 축소) 전부 삭제됐지만, 살아남은 `OnewayDijkstraEngine`은 지금도 이 계약을 따른다.

**벤치마크 solver도 동일하게 갱신됨(2026-08-23)**

- (2026-09-19 갱신) `bi_astar_solver.py`/`bi_dijkstra_solver.py`는 대상 엔진이 삭제되며 함께 삭제됐다 — 지금 남은 것은 `benchmarks/solvers/{dijkstra,astar}_solver.py` 둘이다.
- 두 solver는 `engine.run()`을 호출하지 않고 weight 계산 로직을 자체적으로 복제해서 쓴다(단계별 시간 측정 목적). 둘 다 `compute_distance_only_lookup(engine.G)`를 쓰고(2026-09-19 갱신 — `blocked_tags` 인자는 `profiles.py` 삭제로 더는 없다), `astar_solver.py`의 `engine._min_ratio = ...` 대입(더 이상 존재하지 않는 필드)도 제거해 weight와 `_heuristic`(Haversine)의 전제가 다시 일치한다.
- `benchmarks/runner/test_oneway_shortest_path.py`도 같은 기준으로 갱신했다 — `scoring_engine.py`나 실제 엔진 클래스를 참조하지 않고 자체 재구현하는 구조는 유지하되, weight/heuristic 계산을 production과 동일하게(weight=length(m), heuristic=Haversine 직선거리(m)) 맞췄다. `PROFILE_WEIGHTS`/`compute_custom_score`/`compute_min_ratio`는 삭제했고(profile 블렌딩이 사라졌으므로), `haversine_km`(km)를 `haversine_m`(m)으로 바꿔 `length`(m)와 단위를 맞췄다.

**벤치마크 — 저장소에 커밋된 비교 수치는 없음**

- `benchmarks/runner/test_oneway_shortest_path.py`가 Dijkstra·양방향 Dijkstra·A*의 경로 비용 일치성과 지연시간을 비교하도록 만들어져 있다(`LATENCY_REPEAT`만큼 반복 측정 후 `benchmarks/results/oneway_shortest_path/bidir_astar_latency.csv`에 기록). 이 CSV는 로컬 실행 시에만 생성되며 저장소에는 커밋돼 있지 않다 — 즉 "A*가 실제로 더 빠르다/경로 품질이 같다"는 수치는 이 문서 작성 시점 기준 재현된 적이 없다.
- `benchmarks/run_all_scenarios.py`도 `dijkstra-oneway`를 시나리오 비교 대상에 포함하지만, `oneway_shortest`/`oneway_astar`/`dijkstra-oneway`는 모두 `target_km`을 무시하는 순수 최단경로 알고리즘이라 이 스크립트가 계산하는 거리 이탈(`distance_deviation_km`) 지표는 편도 우회(`oneway_random`) 계열 solver와 직접 비교할 수 없다(스크립트 자체 주석에 명시).
- **아직 확인 안 된 것**: 실제 그래프 규모에서 Dijkstra 대비 A*(Haversine 휴리스틱)의 속도·품질 개선폭. 위 benchmark 스크립트를 로컬에서 실행해 수치를 남기기 전까지는 "왜 이 교체가 유의미한가"를 정량적으로 뒷받침하는 근거가 없다.

## 편도 우회·순환 엔진의 내부 재연결 — Dijkstra → A* 전환(2026-08-23, 역사적 기록)

2026-08-23에 `beam`/`grasp`/`alns`/`rcsp`(편도·순환 8개 엔진 전부: `circular_beam`/
`circular_grasp`/`circular_alns`/`circular_rcsp`/`oneway_beam`/`oneway_grasp`/`oneway_alns`/
`oneway_rcsp`)가 내부적으로 쓰던 `nx.shortest_path`(Dijkstra 기반) 호출을 `PathUtils.astar_path`로
교체해 탐색을 조금 더 빠르게 했다(`custom_score`가 `length`보다 작아질 수 있어 admissible을
지키려고 `min_ratio` 보정을 썼다). (2026-09-19 갱신) 이 8개 엔진은 모두 8축→2축 축소로
삭제됐으므로 이 절이 설명하던 구현(공용 유틸 `PathUtils.min_cost_length_ratio`, 각 엔진의
`_repair_shortest`/`base_shortest` 개별 교체 지점 등)은 더 이상 어떤 코드에도 해당하지
않는다 — 자세한 옛 구현은 git 이력에서 확인한다. 이 절이 도입한 `PathUtils.connect_to()`는
호출부가 하나도 남지 않아(죽은 코드) 2026-09-19에 삭제했다 — 현재 엔진들은 각자 직접
`PathUtils.astar_path()`를 부르거나(`CircularGraspWaypointAlnsEngine`이 쓰는
`grasp_waypoint_common.py`) `nx.astar_path`를 직접 부른다(`OnewayAstarEngine`). `astar_path()`
자체(공용 admissible A* 래퍼)는 여전히 살아 있다 — 2026-09-19부터는 그래프에 ALT가 붙어
있고 `min_ratio >= 1.0`이면 Haversine 대신 ALT를 쓴다(아래 "ALT 서비스 연결" 절).

## 경유지 후보 풀: 단일 풀, cutoff SSSP + lazy 거리표 (2026-08-30)

- `waypoint_pool.py`(`WaypointPoolGenerator`/`WaypointPoolResult`)는 p1(출발지) 기준
  거리 전용(distance-only) cutoff SSSP를 1회 수행해 r_max(=target_m/2) 이내 노드를
  후보 풀로 모은다. 새 경로 탐색 알고리즘이 아니라 이후 조합 단계(beam/GRASP/지역탐색,
  별도 이슈)가 쓸 입력을 준비하는 전처리 단계라 WalkRouteResponse를 반환하지 않고,
  engines/__init__.py에도 등록하지 않는다. 아직 소비하는 조합 단계가 없어
  route_service.py 연동도 하지 않는다.
- r_max = target_m/2 근거: Lewis & Corcoran(J. Heuristics, 2022) 논문에서 확인한
  삼각부등식 — 어떤 라운드트립이 노드 v를 지난다면 길이 ≥ 2·dist(p1,v)가 항상 성립하므로,
  target_m 이내 라운드트립에 포함되려면 dist(p1,v) ≤ target_m/2가 필요조건이다. 경유지
  개수(n)와 무관하게 성립한다.
- r_min(거리 하한)은 두지 않는다 — 위 논문과 후속 논문(SN Comp Sci, 2024, n=3~8
  candidate pool 검증) 모두 하한 없이 r_max 이내 전체를 후보로 쓰고, 하한을 뒷받침하는
  공식도 제시하지 않는다(2026-08-30 논문 원문 확인).
- **풀 내 노드 간 거리는 lazy 계산 + LRU 캐시로 제공한다**(`WaypointPoolResult.distance(u, v)`).
  처음엔 풀 전체 pairwise를 사전 전량 계산해 dict로 들고 있었으나, 실제 서울 그래프
  (노드 160,328개·엣지 223,927개) 벤치마크에서 target_km이 큰 경우(5~8km) pool·pairwise
  항목 수가 함께 급증해 MemoryError로 실패하는 걸 확인해(2026-08-30) lazy+캐시로
  전환했다. `distance(u, v)` 호출 시점에 u를 소스로 하는 cutoff=r_max SSSP를 1회
  계산해 그 행(row) 전체를 캐시하고, 이후 같은 u 조회는 캐시를 그대로 쓴다. 무방향
  그래프라 반대 방향(v가 소스인 행)이 이미 캐시돼 있으면 그것도 재사용한다. 캐시 행
  개수 상한(`_DEFAULT_PAIRWISE_CACHE_ROWS=256`)은 도입 당시엔 논문 근거 없는 임의값이었다 —
  재튜닝 결과는 아래 "캐시 행 개수 상한 재튜닝" 항목 참고.
- lazy+캐시 전환 근거: Lewis & Corcoran(SN Comp Sci, 2024)의 Pareto 지역탐색
  (Algorithm 3/4)도 매 이웃 연산마다 선택된 노드 기준으로 그때그때 도달 트리를
  계산하지, 전체 쌍을 사전에 다 계산해두지 않는다 — 같은 계보의 2023년 논문
  (Lewis, Corcoran, Gagarin, JOCO)에서 처음 나온 neighbourhood operator(정점 u_i
  선택 → RFS/BFS 트리 → 새 해 생성)도 동일한 on-demand 계산 패턴이다.
- pairwise 유도 부분그래프 최적화: r_max 밖의 노드는 어떤 라운드트립에도 포함될 수
  없으므로(위 삼각부등식 근거), lazy SSSP도 원본 그래프 전체가 아니라 p1의 r_max
  유도 부분그래프(`G.subgraph(dist_from_p1.keys())`)에서만 돌려 탐색 범위를 줄였다.
- **실제 그래프 규모 벤치마크(2026-08-30, lazy+캐시 버전)**: 20개 시나리오(target_km
  1~8) 전부 성공, MemoryError 재현 안 됨. 풀 생성(cutoff SSSP 1회) 자체는 target_km과
  무관하게 320~770ms 수준으로 일정함(이전 전량계산 버전은 target_km이 클수록 88~385초까지
  늘어졌었음). 다만 `distance()` 조회 속도는 여전히 pool 크기에 비례해 늘어난다 —
  완전 무작위 균등 샘플링(캐시 히트가 거의 없는 최악 케이스)으로 500쌍 조회 시 pool
  1.4만개 시나리오(target_km=8)에서 약 31초 소요(`benchmarks/runner/waypoint_pool_benchmark.py`로
  재현 가능). 실제 조합 단계(GRASP/ALNS)의 접근 패턴으로는 아래 항목 참고.
- **캐시 행 개수 상한 재튜닝(2026-09-20, #489)**: 조합 단계(`CircularGraspWaypointAlnsEngine`)가
  실제로 붙은 뒤 접근 패턴으로 재튜닝하라는 TODO가 있었다. 프로덕션 확정 조건
  (`grasp-wp-alns`, `num_waypoints=2` — N=2/3/4 비교 이슈 #489에서 N=2 확정)·target_km 3.0/8.0에서
  cache_rows 64/128/256/512/1024/2048을 스윕한 결과, 히트율이 0.9970~0.9972로 전 구간
  사실상 무차이였고(미스 차이 최대 7.5회) elapsed_sec도 15~17초대에서 노이즈 수준으로만
  흔들렸다. 즉 256이 부족해서 문제가 되는 것도, 더 키워서 빨라지는 것도 아니다 — 현재
  값(256)을 그대로 유지한다(재현: `benchmarks/run_cache_rows_tuning.py`, 결과:
  `benchmarks/results/waypoint_pool/cache_rows_tuning.csv`). num_waypoints를 6~8까지
  넓힌 부가 실험에서는 `candidate_limit=2`가 N≥6부터 ALNS 제거 단계를 실패시키는 현상도
  확인됐으나, N=2가 운영값으로 확정되어 있어 당장 조치 대상은 아니다
  (`circular_grasp_waypoint_alns.py`의 `candidate_limit=2` 주석 참고).
- **경유지 개수(N) 기본값 확정(2026-09-20, #489)**: `GraspConfig.num_waypoints=2`가
  단순 하위 호환값이던 것을 실측으로 확정했다. `grasp-wp-alns` 기준 출발지 4곳(밀도
  4계층 대표) × 거리 1/3/5km(설문 기본값) × N 2/3/4 × 시드 10개(360회)에서 N=4가
  N=2보다 평균 53%·최대 81% 더 느린데 품질 이득은 없었다(짝지은 순열검정, 조건 12개,
  Bonferroni 보정 후 유의한 차이는 재통행률 N2 vs N4 하나뿐). 이어서 실제 API 상한
  (`target_km<=10km`, `VAL-DIST-002`)을 커버하도록 7·9km에서 N=2만 추가 검증(같은
  4출발지 × 시드 10 = 80회)한 결과 게이트통과율 1.000(거리편차 0.04km대, 재통행률
  0.004~0.007)으로 서비스 거리 전 구간(1~9km)에서 안정적이었다 — N=2를 그대로
  유지한다(재현: `benchmarks/run_n_waypoint_comparison.py`, 결과:
  `benchmarks/n_waypoint_comparison_results.csv`, 둘 다 미커밋 애드혹 산출물).

## 경유지 후보 풀(편도): 두-소스 타원 cutoff (2026-09-20)

- 진입점은 [waypoint_pool.py](../../src/route_engine/engines/waypoint_pool.py)의
  `WaypointPoolGenerator.build_pool_two_point()`/`WaypointPoolResultTwoPoint`다. 위
  섹션의 왕복 전용 `build_pool()`(수정하지 않음)이 p1=p2인 퇴화 케이스로 보고, 서로
  다른 두 지점(p1=출발지, p2=목적지)으로 일반화한 편도 전용 함수다.
- 채택 조건은 `dist(p1,v) + dist(v,p2) <= budget_m` — p1·p2를 초점으로 하는 타원
  조건이다. 각 소스에서 `cutoff=budget_m` SSSP를 1회씩(총 2회) 수행해 후보 도메인을
  좁힌 뒤, 실제 채택은 이 합 조건 하나로만 판단한다. "두 cutoff 영역이 겹치는가"는
  판단 기준이 아니다(두 영역은 `budget_m >= dist(p1,p2)/2`부터 겹치기 시작하지만, 그
  안의 노드가 합 조건까지 만족한다는 보장은 없다). 왕복 `r_max=target_m/2` 원과
  달리, 편도는 한쪽 구간이 0에 가까우면 다른 쪽이 예산 전체를 써야 하므로 각 소스의
  cutoff 자체가 (거의) `budget_m` 전체여야 한다.
- **target_m 클램프**: 사용자가 요청한 `target_km*1000`이 `dist(p1,p2)`(직선
  최단거리)보다 짧으면 — 물리적으로 불가능한 요청이므로 — `target_m`을
  `dist(p1,p2)`로 보정하고 경고 로그만 남긴 채 계속 진행한다. `None`을 반환하는
  경우는 p1·p2의 최근접 노드를 못 찾거나, p1-p2 사이에 경로 자체가 없는 경우(그래프가
  끊어짐, `NetworkXNoPath`)뿐이다 — "target이 짧아서" `None`이 되는 경우는 없다.
- `dist(p1,p2)`는 `target=p2`를 지정한 조기 종료 다익스트라(`nx.single_source_dijkstra`)로
  먼저 구한다. 이 값 하나로 클램프·`budget_m` 계산·(경로 자체가 없는 경우의) infeasible
  조기 판정을 전부 해결하며, `budget_m` cutoff SSSP 2회보다 훨씬 싸다(아래 실측 참고).
- `budget_m = target_m + slack_ratio * dist(p1,p2)`. `slack_ratio` 기본값은
  5%(`_DEFAULT_SLACK_RATIO`)이며 **실험값/미튜닝**이다 — 실제 그래프 25개 편도
  시나리오 실측(풀 크기라는 대리 지표)에만 근거했고, 이 풀을 실제로 소비할 편도 다중
  경유지 조합 엔진이 아직 없어 완성된 경로 품질로는 검증하지 못했다. 그 엔진이 생기고
  나면 실측 경로 품질 기준으로 재검토한다.
- slack을 절대 m(고정값)이 아니라 `dist(p1,p2)` 비율로 둔 이유: 1차 실측(5개 표본,
  절대 m {0,100,300})에서 여유가 빠듯한 실제 요청(부족분이 직선거리의 10%를 넘는
  경우)을 절대 m 슬랙이 못 구하는 사례가 나왔다 — 25개 시나리오 재표본에서는 클램프
  도입 전 기준으로 24%(6/25)가 클램프 없이는 target이 직선거리보다 짧은 요청이었다.
- **실제 그래프 규모 벤치마크(2026-09-20, clamp+slack_ratio 적용 후)**: 편도 시나리오
  25개 × {데이터셋 target_km, 경계근접(직선거리×1.02)} × `slack_ratio` {0/5/10/20%} =
  200건 전부 성공(`feasible=True`), MemoryError 재현 안 됨. 호출당 평균 834ms(중앙값
  719ms, 최대 2259ms) — `dist(p1,p2)` 조기종료 조회를 앞에 넣었는데도 `budget_m`
  cutoff SSSP 2회가 여전히 대부분을 차지한다. `slack_ratio=0`으로 두면 클램프된
  케이스(요청 `target_km`이 직선거리보다 짧아 `dist(p1,p2)`로 보정된 경우) 중
  최솟값이 풀 크기 1개(`oneway_02`, `dist(p1,p2)`=2136m)까지 떨어진다 — 기본값
  `slack_ratio=5%`는 이 경우를 84개로 되살린다(84배). 순환 대비 풀 크기 비율은
  데이터셋 조건에서 `slack_ratio` 0%→20% 구간 중앙값 0.43배→1.03배, 경계근접
  조건에서는 0.13배→0.66배로, 어느 조건도 순환보다 극단적으로 커지지는 않는다.
- **구축 단계 연결(2026-09-20, feat/496)**: 이 풀을 직접 소비하는 조합 엔진은 여전히
  없지만, `engines/grasp_waypoint_common.py::construct_initial_route()`와
  `waypoint_route_builder.py::build_cycle_route()`가 `end_node` 파라미터로 이 풀의
  `dist_from_p2`와 `_rank_next_waypoint_candidates()`의 `p2`(커밋 79a3515)를 받아 실제
  경로를 연결할 수 있는 상태는 됐다 — `end_node=None`(기본값)이면 두 함수 모두 기존
  순환 동작과 완전히 동일하다. `route_service.py`·조립 계층(`waypoint_engine_assembly.py`)이
  이 풀(`build_pool_two_point`)을 만들어 그 함수들에 넘기는 프로덕션 배선은 아직 빠져
  있어 "완성된 편도 다중 경유지 조합 엔진"은 여전히 없다 — 위 `slack_ratio` 미검증
  항목도 그대로 유효하다. 정제 단계(local/VND/VNS/ALNS)와 조립 루프까지 `end_node`를
  넓히는 작업은 별도 이슈로 남겨뒀다. 재현:
  [waypoint_pool_two_point_benchmark.py](../../benchmarks/runner/waypoint_pool_two_point_benchmark.py).

## Planar 랜드마크 선택 독립 함수 (2026-08-30)

ALT(A* + Landmark + Triangle inequality)의 Planar 랜드마크 선택법을 독립 함수로
구현했다. 공용 인프라는 [landmark_shared.py](../../src/route_engine/landmark_shared.py),
선택법 자체는 [landmark_planar.py](../../src/route_engine/landmark_planar.py)의
`select_landmarks_planar()`이다. 어떤 엔진에도 연결하지 않았다(2026-09-12에 이 선택법이
최단거리 서비스에 연결됐다 — 아래 "ALT 서비스 연결" 절 참고). 당시 기준으로는 프로덕션
`OnewayAstarEngine`은 weight=length(거리 전용)로 바뀌면서 Haversine 휴리스틱만으로도
admissible해 랜드마크 ALT 자체를 쓰지 않는다(2026-08-23, 아래 "oneway_shortest 엔진"
절 참고). `precompute_landmarks()`/`_select_landmarks()`/`landmark_dist`가 그 때
전부 제거된 뒤로 저장소에 ALT를 쓰는 프로덕션 코드는 없다.

### 입력·출력과 공유 인프라

- `LandmarkTable = dict[int, dict[int, float]]`(랜드마크 노드 ID → {노드 ID: 거리(m)})가
  세 선택법(Random/Farthest/Planar)이 공유할 사전계산 표 구조다. 현재는 Planar만
  구현했다.
- `precompute_landmark_distances(G, landmarks, weight="length")`: 랜드마크별
  `nx.single_source_dijkstra_path_length`로 전체 노드까지의 실제 도로망 거리를 구해
  `LandmarkTable`을 만든다. 무방향 그래프 기준이라 `dist(L,u) == dist(u,L)`이며
  정방향 표만으로 충분하다. 도달 불가 노드는 표에 아예 없다.
- `alt_heuristic(landmark_dist, u, v)`: 삼각부등식 `h(u,v) = max_L |dist(L,u) - dist(L,v)|`.
  랜드마크가 u 또는 v 중 하나에 도달 못 하면 그 랜드마크는 건너뛰고, 전부 건너뛰면
  0.0(정보 없음이지만 여전히 admissible)을 반환한다.
- `build_alt_heuristic(G, landmarks, weight="length")`: 위 두 함수를 묶어
  `nx.astar_path(heuristic=...)`에 바로 넘길 수 있는 클로저와 `LandmarkTable`을
  함께 반환한다.
- `_largest_component_nodes(G)`: `PathUtils.find_nearest_node`와 동일하게 최대
  연결요소로 후보를 제한한다 — 실제 탐색 시작점도 이 요소 안에서만 잡히므로,
  랜드마크도 여기서 고르면 모든 탐색 쌍에 대해 도달 가능함을 보장할 수 있다.

### `select_landmarks_planar(G, n_sectors)` 구현 규칙

1. `_largest_component_nodes(G)`로 후보를 제한하고, 그 노드들의 (lat, lon)
   산술평균을 centroid로 쓴다. 서울 시내 규모에서는 구면 곡률로 인한 오차가
   무시할 만하다고 가정했고, 실측 검증은 하지 않았다.
2. centroid 기준 각 노드의 각도를 `atan2(dlon, dlat)`로 구한다. dlon은
   `cos(centroid 위도)`로 보정한 단순 등장방형(equirectangular) 근사다 —
   정북 기준 시계방향 bearing과 같은 값이 나온다.
3. `sector_width = 2π / n_sectors`로 섹터를 나누고, 섹터마다 centroid에서
   Haversine 직선거리가 가장 먼 노드 1개만 남긴다(동률이면 먼저 순회된 노드 유지).
4. 노드가 없는 섹터는 랜드마크를 내지 않는다 — **반환 개수가 `n_sectors`보다
   적을 수 있다.** 좌표 분포에 따른 예상 동작이며 버그가 아니다.
5. Farthest 선택법과 달리 도로망 거리 계산(SSSP)이 전혀 필요 없어 선택 자체는
   훨씬 저렴하다(좌표만으로 계산).

### 논문 대조

- Goldberg & Harrelson, *Computing the Shortest Path: A\* Search Meets Landmarks*
  (2005)의 Planar 선택법 설명(좌표 평면을 섹터로 나눠 섹터별 최원거리 노드를
  선택)을 따랐다. 원 논문의 공간 분할(예: quadtree·space-filling curve) 대신
  centroid 기준 각도 섹터로 단순화했다 — 이 단순화가 논문의 실제 성능 특성과
  얼마나 가까운지는 확인하지 않았다.
- Random/Farthest 선택법은 이번에 구현하지 않았다(2026-09-12에 독립 함수로
  구현했다 — 아래 "Random 랜드마크 선택 독립 함수"·"Farthest 랜드마크 선택
  독립 함수" 절 참고). 티켓이 요구한 "Random/Farthest
  대비 h(n) 품질·탐색 노드 수 비교 벤치마크"는 그 두 선택법이 없어 아직 수행하지
  못했다 — `landmark_shared.py`의 `LandmarkTable`/`verify_admissible` 등 공용
  인터페이스는 이후 `landmark_random.py`/`landmark_farthest.py`를 같은 패턴으로
  추가할 것을 가정하고 설계했다.

### Admissibility 검증

- `AdmissibilityReport`/`verify_admissible(G, landmark_dist, weight, pairs)`
  (`landmark_shared.py`)는 호출자가 준 (u, v) 표본마다 `h_ALT(u,v) <= 실제
  최단거리`와 `h_Haversine(u,v) <= 실제 최단거리`를 함께 검사하고, 위반 수·최대
  위반량·평균 h 값(ALT/Haversine/실제)을 반환한다. 표본 생성은 이 함수의
  책임이 아니다.
- `alt_heuristic`의 admissibility는 삼각부등식으로 항상 증명되는 성질이다
  (`landmark_dist`가 탐색과 같은 weight로 정확히 계산된 실제 최단거리인 한).
  `verify_admissible`은 이 성질이 구현에서 실제로 깨지지 않는지 확인하는
  회귀 검증 도구이지, 별도의 수학적 근거를 새로 세우는 것은 아니다.

### 실행·검증·복구

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_landmark_planar.py -q
```

- 2026-08-30, 로컬 pytest 실행에서 5개 테스트 전부 통과. 섹터 8개 고정 배치
  (45도 간격 외곽 노드) 정확한 배정, 좁은 각도 분포에서 일부 섹터가 비어
  `n_sectors`보다 적게 반환되는 경우, `n_sectors < 1` 거부, 5×5 grid에서 전체
  쌍(300쌍) admissibility 위반 0건, `alt_heuristic` 수치 손계산 대조를 확인했다.
- 최초 섹터 배정 테스트는 외곽 노드를 섹터 "경계"(정확히 45도 배수)에 둬서
  `atan2`/`radians` 변환의 부동소수 반올림으로 인접 섹터로 흔들리는 실패를
  겪었다 — 노드를 섹터 "중앙" 각도(22.5도 오프셋)로 옮겨 해결했다. 구현
  로직 자체의 결함은 아니었다.
- toy 그래프(5×5 grid, 반경형 8노드)로만 검증했다. 실제 서울 그래프
  규모(15만+ 노드)에서의 선택 시간·섹터 분포·A* 탐색량 감소 효과, Random/Farthest
  대비 비교, 어떤 엔진에도 연결한 실행은 아직 확인하지 않았다.
- 문제 발생 시 이 두 파일과 단위 테스트부터 확인한다. 어떤 엔진·API·DB도
  변경하지 않아 복구가 필요 없다.

## Avoid 랜드마크 선택 독립 함수 (2026-08-30)

ALT의 Avoid 랜드마크 선택법을 독립 함수로 구현했다. 진입점은
[landmark_avoid.py](../../src/route_engine/landmark_avoid.py)의
`select_landmarks_avoid()`이며, 공용 인프라는 Planar와 동일하게
[landmark_shared.py](../../src/route_engine/landmark_shared.py)를 그대로 쓴다 —
`weight(v)` 계산에 `alt_heuristic`을 그대로 재사용해서 이번에 공용 모듈에 새로
추가한 함수는 없다. Planar와 마찬가지로 어떤 엔진에도 연결하지 않았다(2026-09-12에
Planar만 서비스에 연결됐고, Avoid는 전처리 비용 대비 이득이 확인되지 않아
`alt_runtime`의 지원 목록에서 빠졌다 — 아래 "ALT 서비스 연결" 절 참고).

### 알고리즘(원 논문 기준)

좌표가 아니라 그래프 구조(최단경로 트리)로 "기존 랜드마크가 잘 못 덮는 영역"을
찾는다. 이미 뽑힌 랜드마크 집합 S가 있는 상태에서 k회 반복하며 매번:

1. 루트 r을 무작위로 고르고 최단경로 트리(SPT) T_r을 만든다
   (`nx.dijkstra_predecessor_and_distance`).
2. 모든 노드 v의 `weight(v) = dist(r,v) - (S 기준 ALT 하한)`을 구한다. S가
   비어있으면 하한이 항상 0이라 `weight(v) = dist(r,v)`다 — 이 경우 이후 단계는
   "루트에서 가장 무거운 가지를 따라 리프까지 내려가는" 동작으로 줄어든다.
3. `size(v)`를 후위 순회로 구한다 — v의 서브트리(자신 포함)에 기존 랜드마크가
   하나라도 있으면 0, 없으면 서브트리 전체 weight 합.
4. size가 가장 큰 노드 w를 고르고(기존 랜드마크가 없는, 가장 안 덮인 영역), w에서
   시작해 항상 size가 가장 큰 자식으로 내려가 리프에 도달하면 그 리프를 새
   랜드마크로 추가한다. 동점은 노드 ID가 작은 쪽을 우선한다(원 논문에 없는 이
   구현의 결정).

### 구현이 원 논문과 다른 점

- **참고 논문 재확인**: 작업 티켓은 Goldberg, Kaplan, Werneck의 "Reach for A*"
  (2006, MSR-TR-2005-132)를 인용했다. 2026-08-30 원문(도입부·관련 연구)을
  확인했으나 Avoid 선택법 자체는 없었다(전체를 다 읽지는 못함). size(v)/서브트리
  하강 pseudocode가 명확히 나온 곳은 같은 저자 그룹의 더 이른 논문인
  Goldberg & Werneck, *Computing Point-to-Point Shortest Paths from External
  Memory* (2005) §6.3.4였고, 이 구현은 그 절을 기준으로 삼았다.
- **루트 선택**: 원 논문은 "기존 랜드마크에서 먼 노드를 더 높은 확률로 고르면
  결과가 더 좋았다"고 언급하지만, 이 구현은 단순 균등 무작위(`random.Random(seed).choice`)
  만 쓴다 — 가중 샘플링은 구현하지 않았다.
- **SPT의 동점 predecessor**: `nx.dijkstra_predecessor_and_distance`가 동점
  최단경로로 여러 predecessor를 반환할 수 있는데, 첫 번째만 부모로 써서 단일
  트리로 단순화했다(`_subtree_children`).
- **완전 소진 시 방어적 처리**: 최대 연결요소가 이미 기존 랜드마크로 전부
  '덮여서'(모든 노드의 size가 0) 더 이상 안 덮인 리프를 찾을 수 없는 극단적인
  경우, 아직 안 뽑힌 노드 중 하나를 무작위로 대신 골라 항상 서로 다른 k개를
  반환한다 — 원 논문에는 없는 처리다.

### 전처리 비용

- 반복(랜드마크 1개)마다 SSSP 2회(루트 SPT 1회 + 새 랜드마크 자체 거리표 1회)가
  필요해 Farthest(반복당 SSSP 1회)보다 크다.
- 게다가 매 반복 전체 노드에 대해 `alt_heuristic`(현재까지 뽑힌 랜드마크 수만큼
  순회)을 다시 계산해야 해서, 랜드마크 수 k가 늘수록 반복당 비용도 함께
  늘어난다(반복당 O(n·|S|)). k=16, n=16만 규모에서 실제로 얼마나 걸리는지는
  아직 실측하지 않았다 — Random/Farthest/Planar 대비 벤치마크(아래 "미확인"
  항목)에서 함께 측정해야 한다.

### Admissibility 검증

Planar와 동일하게 `landmark_shared.py`의 `verify_admissible`을 그대로 쓴다 —
Avoid로 고른 랜드마크도 admissibility는 삼각부등식으로 항상 증명되는 성질이라
(`landmark_dist`가 실제 최단거리인 한) 별도 새 검증 로직이 필요 없다.

### 실행·검증·복구

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_landmark_avoid.py -q
```

- 2026-08-30, 로컬 pytest 실행에서 8개 테스트 전부 통과. 손으로 계산한 고정
  트리(노드 6개)로 `_select_avoid_landmark`의 핵심 로직 3가지를 직접 검증했다 —
  기존 랜드마크가 없을 때 가장 무거운 가지를 따라 내려가는 것, 기존 랜드마크가
  있는 서브트리를 완전히 건너뛰는 것(size=0 오염이 부모까지 전파), 남은 후보가
  루트 자신뿐인 극단 케이스. 6×6 grid에서는 `select_landmarks_avoid`가 k개
  distinct 노드를 반환하는지, seed 고정 시 재현되는지, k가 너무 크면 거부하는지,
  3개 seed에서 전체 쌍 admissibility 위반이 0건인지 확인했다.
- **미확인**: 실제 서울 그래프 규모(15만+ 노드)에서의 선택 시간(위 "전처리
  비용" 참고), Random/Farthest/Planar 대비 h(n) 품질·탐색 노드 수 비교
  벤치마크, 어떤 엔진에도 연결한 실행. Random/Farthest 자체도 아직 구현하지
  않아 4개 선택법을 한 번에 비교하는 벤치마크는 그것부터 필요하다(Random/Farthest는
  2026-09-12에 구현해 선택법 4종이 모두 갖춰졌고, 비교 벤치마크는 아직 남아 있다).
- 문제 발생 시 이 두 파일과 단위 테스트부터 확인한다. 어떤 엔진·API·DB도
  변경하지 않아 복구가 필요 없다.

## Random 랜드마크 선택 독립 함수 (2026-09-12)

ALT의 Random 랜드마크 선택법을 독립 함수로 구현했다. 진입점은
[landmark_random.py](../../src/route_engine/landmark_random.py)의
`select_landmarks_random()`이며, 공용 인프라는 Planar/Avoid와 동일하게
[landmark_shared.py](../../src/route_engine/landmark_shared.py)를 그대로 쓴다 —
이번에 공용 모듈에 새로 추가한 함수는 없다(모듈 docstring의 선택법 목록에 Avoid를
더한 것이 유일한 수정이다). Planar/Avoid와 마찬가지로 어떤 엔진·API·DB에도
연결하지 않았다.

### 입력·출력

- 입력: `G`(무방향 그래프), `k`(랜드마크 개수), 키워드 전용 `seed`(기본 0).
- 출력: 서로 다른 노드 ID `k`개의 `list[int]`. 거리표는 반환하지 않는다 — 호출자가
  `precompute_landmark_distances(G, landmarks, weight="length")`로 따로 만든다.
  선택법 4종이 모두 같은 계약이라 서로 교체해 끼울 수 있다.
- `k < 1`이거나 `k`가 최대 연결요소의 노드 수보다 크면 `ValueError`.

### `select_landmarks_random(G, k, *, seed=0)` 구현 규칙

1. `_largest_component_nodes(G)`로 후보를 최대 연결요소로 제한한다 — 실제 탐색
   시작점도 이 요소 안에서만 잡히므로, 모든 탐색 쌍에서 도달 가능한 랜드마크가 된다.
2. `random.Random(seed).sample(nodes, k)`로 중복 없이 k개를 뽑는다. 전역 `random`
   상태를 건드리지 않아 호출자의 다른 난수 흐름에 영향을 주지 않는다.
3. SSSP도 좌표 계산도 하지 않는다 — 선택 자체의 비용이 4종 중 가장 낮다
   (Planar는 좌표 1패스, Farthest는 SSSP k회, Avoid는 반복당 SSSP 2회).

### 논문 대조

- Goldberg & Harrelson, *Computing the Shortest Path: A\* Search Meets Graph
  Theory* (SODA 2005)가 Farthest/Planar의 성능을 견줄 때 기준선으로 쓴 무작위
  선택을 그대로 옮겼다. 알고리즘에 해석의 여지가 없어 Planar/Avoid와 달리 원
  논문과 다르게 구현한 부분이 없다.
- 이 저장소의 Planar 절은 같은 논문을 *A\* Search Meets Landmarks*로 적었는데
  원 제목은 *A\* Search Meets Graph Theory*다. 2026-09-12 작업에서 원문 PDF를 다시
  열어 대조하지는 않았고, Planar 절의 문장도 그대로 두었다 — 표기를 어느 쪽으로
  통일할지는 남은 판단이다.

### Admissibility 검증

Planar/Avoid와 동일하게 `landmark_shared.py`의 `verify_admissible`을 그대로 쓴다.
어떤 방식으로 고르든 `alt_heuristic`의 admissibility는 삼각부등식으로 항상
증명되는 성질이라(`landmark_dist`가 탐색과 같은 weight로 계산된 실제 최단거리인 한)
새 검증 로직이 필요 없다 — 무작위 선택도 예외가 아니다.

### 실행·검증·복구

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_landmark_random.py -q
```

- 2026-09-12, 로컬 pytest 실행에서 7개 테스트 전부 통과. 6×6 grid에서 k개 distinct
  노드 반환, 같은 seed 재현, 다른 seed(0/1)의 결과 불일치, `k < 1` 거부,
  `k > 최대 연결요소 노드 수` 거부, seed 0/1/2 각각에서 전체 쌍(630쌍)
  admissibility 위반 0건을 확인했다.
- **미확인**: 실제 서울 그래프 규모(15만+ 노드)에서의 선택 시간과 h(n) 품질,
  Farthest/Planar/Avoid 대비 비교 벤치마크, 어떤 엔진에도 연결한 실행.
- 문제 발생 시 이 파일과 단위 테스트부터 확인한다. 어떤 엔진·API·DB도 변경하지
  않아 복구가 필요 없다.

## Farthest 랜드마크 선택 독립 함수 (2026-09-12)

ALT의 Farthest 랜드마크 선택법을 독립 함수로 구현했다. 진입점은
[landmark_farthest.py](../../src/route_engine/landmark_farthest.py)의
`select_landmarks_farthest()`이며, 공용 인프라는
[landmark_shared.py](../../src/route_engine/landmark_shared.py)의
`_largest_component_nodes`/`precompute_landmark_distances`를 그대로 쓴다 — 이번에
공용 모듈에 새로 추가한 함수는 없다. 다른 세 선택법과 마찬가지로 어떤 엔진·API·DB에도
연결하지 않았다.

### 입력·출력

- 입력: `G`, `k`, 키워드 전용 `weight`(기본 `"length"`), `seed`(기본 0). `weight`는
  `precompute_landmark_distances`로 그대로 넘어가므로, 나중에 거리표를 만들 때와
  **같은 weight**를 써야 선택 기준과 실제 휴리스틱이 어긋나지 않는다.
- 출력: 서로 다른 노드 ID `k`개의 `list[int]`. **뽑힌 순서를 유지한다** — 앞쪽이
  먼저 뽑힌, 즉 그 시점의 랜드마크 집합에서 더 멀리 떨어졌던 노드다.
- `k < 1`이거나 `k`가 최대 연결요소의 노드 수보다 크면 `ValueError`(Random과 동일).

### `select_landmarks_farthest(G, k, *, weight="length", seed=0)` 구현 규칙

1. `_largest_component_nodes(G)`로 후보를 제한하고, 첫 랜드마크를
   `random.Random(seed).choice`로 무작위로 고른다.
2. 랜드마크를 추가할 때마다 그 랜드마크 1개에 대해 `precompute_landmark_distances`를
   1회 호출하고, 그 결과로 노드별 `min_dist(v) = min_{L in S} dist(L, v)`를
   갱신한다. 전체 SSSP 횟수는 정확히 k회다.
3. 아직 뽑히지 않은 후보 중 `min_dist(v)`가 가장 큰 노드를 다음 랜드마크로 고른다.
   동점은 노드 ID가 작은 쪽을 우선한다(재현성을 위한, 원 논문에 없는 이 구현의 결정).
4. `min_dist`는 그 노드에 **실제로 도달한** 랜드마크만으로 계산하고, 어떤
   랜드마크에서도 도달하지 못한 노드는 후보에서 아예 제외한다 — 그런 노드는 ALT
   하한을 전혀 받지 못해 "가장 먼 노드"로 뽑을 이유가 없다. 무방향 그래프는 최대
   연결요소 안에서 서로 모두 도달 가능하므로 이 제외가 실제로 일어나지 않는다.
5. (방어적 처리) 4번에도 불구하고 도달 가능한 후보가 다 떨어져 k개를 못 채우면
   `ValueError`를 낸다. 조용히 k개보다 적게 반환하거나 하한을 못 주는 노드를
   랜드마크로 넣는 것보다 낫다고 판단한, 원 논문에 없는 이 구현의 결정이다.

### 전처리 비용

- 반복(랜드마크 1개)당 SSSP 1회 + `min_dist` 갱신 O(n)이라 전체 O(k·(SSSP + n)).
- Avoid(반복당 SSSP 2회 + O(n·|S|))보다 싸고, Planar(SSSP 0회, 좌표 1패스)와
  Random(SSSP 0회)보다 비싸다. 실제 서울 그래프에서의 절대 시간은 아직 실측하지
  않았다.

### 논문 대조

- Goldberg & Harrelson (SODA 2005, 제목 표기는 위 Random 절 참고)의 farthest
  선택법 — "현재 랜드마크 집합까지의 거리가 최대인 노드를 반복해서 더한다" — 의
  반복 단계를 그대로 따랐다.
- **첫 랜드마크가 원 논문과 다르다**: 원 논문은 무작위 시작점에서 *가장 먼* 노드를
  첫 랜드마크로 삼지만, 이 구현은 무작위로 고른 노드 자체를 첫 랜드마크로 쓴다.
  SSSP 1회를 아끼는 대신 첫 랜드마크가 그래프 외곽으로 밀리지 않는다. 2번째
  랜드마크부터는 규칙이 같다. 이 차이가 h(n) 품질에 얼마나 영향을 주는지는
  측정하지 않았다.
- 동점 처리(노드 ID가 작은 쪽)와 도달 불가 노드 제외는 원 논문에 없는 이 구현의
  결정이다. 2026-09-12 작업에서 원문 PDF를 다시 열어 대조하지는 않았다.

### Admissibility 검증

Planar/Avoid/Random과 동일하게 `landmark_shared.py`의 `verify_admissible`을 그대로
쓴다. Farthest가 고르는 "서로 멀리 떨어진" 랜드마크는 h(n)을 크게 만들 뿐
admissibility 조건 자체를 바꾸지 않는다 — 삼각부등식으로 항상 성립한다.

### 실행·검증·복구

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_landmark_farthest.py -q
```

- 2026-09-12, 로컬 pytest 실행에서 9개 테스트 전부 통과. 노드 5개를 100m 간격으로
  이은 일직선 그래프에서 선택 순서를 손계산과 대조했다 — 끝점(0번)에서 시작하면
  `[0, 4, 2, 1, 3]`, 안쪽 노드(3번)에서 시작하면 `[3, 0, 1, 2]`로, "반대쪽 끝 →
  가운데 → 동점이면 작은 ID" 순서가 그대로 나온다. 6×6 grid에서는 k개 distinct
  노드 반환, 같은 seed 재현, 다른 seed(0/1)의 결과 불일치, `k < 1`·`k > 노드 수`
  거부, seed 0/1/2 각각에서 전체 쌍(630쌍) admissibility 위반 0건을 확인했다.
- 일직선 그래프 테스트의 첫 랜드마크(seed 2 → 0번, seed 0 → 3번)는
  `random.Random(seed).choice`가 `_largest_component_nodes`의 반환 순서에 의존한다.
  그 순서가 바뀌면 테스트 기대값도 다시 계산해야 한다.
- **미확인**: 실제 서울 그래프 규모(15만+ 노드)에서의 선택 시간(위 "전처리 비용"
  참고)과 h(n) 품질, Random/Planar/Avoid 대비 비교 벤치마크, 어떤 엔진에도 연결한
  실행.
- 문제 발생 시 이 파일과 단위 테스트부터 확인한다. 어떤 엔진·API·DB도 변경하지
  않아 복구가 필요 없다.

## A*·ALT 점대점 벤치마크 (2026-09-12)

Planar·Avoid·Random·Farthest 4종을 갖춘 뒤, 같은 (출발, 도착) 쌍에 같은 weight를 주고
휴리스틱만 바꿔가며 Dijkstra / Haversine A* / ALT 4종을 한 번에 비교하는 벤치마크를
추가했다. 구성 파일은 셋이다.

- [benchmarks/build_shortest_path_scenarios.py](../../benchmarks/build_shortest_path_scenarios.py):
  시나리오 데이터셋 생성기. 산출물 [benchmarks/datasets/shortest_path.json](../../benchmarks/datasets/shortest_path.json)도 함께 커밋한다.
- [benchmarks/runner/_astar_instrumented.py](../../benchmarks/runner/_astar_instrumented.py):
  `nx.astar_path` 복제판. 확장 노드 수를 세기 위한 것이다.
- [benchmarks/runner/alt_shortest_path.py](../../benchmarks/runner/alt_shortest_path.py): 러너.

### 목적과 경계

- **목적**: 휴리스틱이 탐색 공간을 실제로 얼마나 줄이는지, 그 대가로 전처리에 얼마를
  쓰는지를 같은 조건에서 관측한다.
- **경계**: 이 벤치마크는 측정만 한다. `src/` 아래 코드는 읽기만 하고 한 줄도 바꾸지
  않았으며, 어떤 엔진·API·DB에도 연결하지 않았다. 현재 프로덕션 `OnewayAstarEngine`은
  weight=length(거리 전용)라 Haversine만으로도 admissible해 랜드마크 ALT를 쓰지 않는다
  (2026-08-23, 아래 "oneway_shortest 엔진" 절 참고).
- **어느 방식을 채택할지는 이 문서에서 판단하지 않는다.** 관측값만 남긴다.

### 시나리오 설계

출발 노드는 `landmark_shared._largest_component_nodes(G)`가 주는 최대 연결요소 안에서만
고른다 — 실제 엔진의 `PathUtils.find_nearest_node`와 같은 규칙이라, 여기서 고른 쌍은
프로덕션 탐색이 실제로 마주칠 수 있는 쌍이다.

| tier | 직선거리 | 우회 비율 | 개수 | 왜 |
| --- | --- | --- | ---: | --- |
| `near` | 0.5 ~ 1.5km | 제한 없음 | 4 | 짧은 탐색에서 전처리 비용이 회수되는지 |
| `mid` | 3 ~ 5km | 제한 없음 | 4 | 일반적인 편도 요청 규모 |
| `long` | 8 ~ 12km | 제한 없음 | 4 | 탐색 공간이 가장 커지는 구간 |
| `detour` | 1 ~ 4km | 1.6 이상 | 4 | 한강·철도 횡단처럼 직선거리가 실제 거리를 크게 밑도는 구간 |
| `same` | 출발 = 도착 | — | 1 | 즉시 종료(거리 0, 확장 1회)하는지 |
| `unreachable` | 다른 연결요소 | — | 1 | 모든 방식이 "경로 없음"으로 끝나는지 |

우회 비율은 `실제 도로거리 / 직선거리`이며, 도로거리는 Dijkstra로 직접 계산해 확인한다
(`build_shortest_path_scenarios.qualifies`). 출발 노드 1개마다 SSSP를 1회만 돌리고 그
결과로 아직 못 채운 tier를 한 번에 보되, 한 출발 노드에서 tier마다 최대 1쌍만 가져와
출발지가 한곳에 몰리지 않게 한다.

**`unreachable` tier는 현재 artifact에서 비어 있다.** `walk_graph_v1.pkl`
(`v2-2026-08-25`)은 연결요소가 1개(전체 160,197노드)라 도달 불가 쌍이 존재하지 않는다.
생성기는 이때 오류로 멈추지 않고 이유를 `meta.notes`에 남기고 나머지 tier를 정상
생성한다 — 그래서 데이터셋은 18개가 아니라 **17개**다. 러너의 "경로 없음" 처리 경로는
[tests/unit/test_alt_shortest_path_runner.py](../../tests/unit/test_alt_shortest_path_runner.py)가
고립 노드를 붙인 toy 그래프로 따로 검증한다.

```bash
./.venv/Scripts/python.exe -m benchmarks.build_shortest_path_scenarios --seed 42
```

### 측정 정의

- **popped**: 우선순위 큐에서 노드를 꺼낸 횟수(= 확장한 노드 수). 같은 노드가 더 나은
  경로로 다시 들어왔다가 꺼내지면 중복해서 센다. 시간과 달리 같은 입력에서 결정적이라
  휴리스틱이 탐색 공간을 얼마나 줄였는지를 머신 상태와 무관하게 보여준다.
- **pushed**: 큐에 넣은 횟수. 시작 노드를 올리는 최초 1회를 포함한다.
- 두 값은 `_astar_instrumented.astar_path_instrumented`가 센다. `nx.astar_path`를
  그대로 복제하고 카운터만 더한 것이라 탐색 순서·결과 경로는 원본과 같다
  (원본 라이선스 BSD-3, 복제 버전은 모듈 docstring에 적어 뒀다).
  **`dijkstra` 행의 popped/pushed는 h=0으로 돌린 같은 계측판에서 잰다**(A* with h=0은
  Dijkstra와 같은 탐색이다). 시간은 `nx.shortest_path(method="dijkstra")`로 재므로,
  `dijkstra` 행의 시간과 확장 노드 수는 서로 다른 구현에서 나온 값이다.
- **search_mean_s / search_median_s / search_max_s**: 계측 없는 탐색을 warmup 1회 +
  `--repeats`회 반복해 잰 초 단위 시간. `test_oneway_shortest_path.time_repeated`와 같은
  방식으로 측정 중 gc를 끈다. 확장 노드 수를 세는 패스는 시간 측정에 섞지 않는다.
- ⚠ **시간 비교에 섞인 구현 차이**: `haversine`과 ALT 4종의 시간은 모두 위 계측판에서
  나오지만 `dijkstra`의 시간만 `nx.shortest_path`(라이브러리 구현)에서 나온다. 그래서
  ALT 사이의 시간 비교와 `haversine` 대비 시간 비교는 같은 구현끼리의 비교지만,
  `dijkstra` 대비 시간 비교에는 알고리즘 차이와 구현 차이가 함께 들어 있다. popped는
  6개 방식 모두 같은 계측판에서 세므로 이 문제가 없다 — 방식 간 비교는 popped 쪽이
  더 깨끗하다.
- **select_s**: 랜드마크 선정 시간. **table_s**: 거리표(`precompute_landmark_distances`)
  생성 시간. 둘 다 `(방식, k, seed)` 조합당 전체 실행에서 1회만 수행하고 모든 시나리오가
  재사용하므로, 행마다 같은 값이 반복해서 찍힌다.
- **table_entries**: 거리표의 총 항목 수(모든 랜드마크 행의 노드 수 합).
  **table_bytes**: `pickle.dumps(table)` 바이트 수.
- **k_actual**: 실제로 뽑힌 랜드마크 수. Planar는 `n_sectors=k`로 호출하는데 노드가 없는
  섹터는 랜드마크를 내지 않아 `k_requested`보다 적을 수 있어 따로 기록한다.
- **cost_match**: 그 방식의 경로 비용이 Dijkstra 비용과 1e-6m 이내인지.
  **path_valid**: 끝점이 맞고 이웃 노드끼리 실제 간선으로 이어져 있는지.
- **alt_violations / haversine_violations**: `(방식, k, seed)` 조합마다 시나리오 전체
  `(start, end)` 쌍으로 `landmark_shared.verify_admissible`을 돌려 얻은 위반 수.

weight는 전 구간에서 `test_oneway_shortest_path.distance_weight`(= `max(1.0, length)` m)
하나로 고정하고, 랜드마크 선정·거리표·admissibility 검증에도 같은 함수를 넘긴다. 거리표를
다른 weight로 만들면 삼각부등식 하한이 탐색 비용의 하한이 아니게 되어 admissibility가
깨질 수 있다. Haversine 휴리스틱은 프로덕션 `OnewayAstarEngine._heuristic`과 같은 공식
(`PathUtils._haversine_m`)이다.

### 실행·검증·복구

```bash
./.venv/Scripts/python.exe -m benchmarks.build_shortest_path_scenarios --seed 42
./.venv/Scripts/python.exe -m benchmarks.runner.alt_shortest_path --k 4 8 16 --seeds 0 1 2 --repeats 5
./.venv/Scripts/python.exe -m pytest tests/unit/test_alt_shortest_path_runner.py -q
```

- 2026-09-12, 로컬 pytest 실행에서 `test_alt_shortest_path_runner.py` 25개 전부 통과.
  계측 A*가 `nx.astar_path`와 같은 경로를 내는지, 경로 없음에 `NetworkXNoPath`를 올리는지,
  6개 방식이 모두 Dijkstra와 비용이 맞고 유효한 경로인지, `same`이 거리 0·확장 1회
  이하인지, 고립 노드를 붙인 그래프에서 `no_path`가 예외 없이 기록되는지, 장벽
  grid(강·다리 모형)에서 ALT의 popped가 Haversine 이하인지, 결과 행에 선언된 CSV 컬럼이
  전부 있는지, 시나리오 생성기의 tier 판정(직선거리 경계·우회 비율 경계)을 확인했다.
- 결과는 `benchmarks/results/shortest_path/{YYYYMMDD-HHMMSS}/`에 `results.csv`,
  `summary.json`, `results.metadata.json`(코드 커밋·artifact 해시·패키지 버전)로 남는다.
  실행할 때마다 새 폴더가 생기는 산출물이라 `.gitignore`로 제외한다 — 커밋하는 것은
  생성 스크립트와 시나리오 JSON뿐이다.
- 이 벤치마크는 `src/`를 변경하지 않으므로 복구 절차가 필요 없다. 결과가 이상하면
  위 세 파일과 단위 테스트부터 확인한다.
- ⚠ `networkx`를 올릴 때는 원본 `astar_path()`와 `_astar_instrumented.py`를 다시
  대조해야 한다. 원본이 바뀌면 이 복제본은 조용히 다른 알고리즘이 된다.

### 관측 (2026-09-12)

- 환경: Windows-11-10.0.26200, Python 3.12.14, networkx 3.6, numpy 2.4.3.
- 입력: `artifacts/walk_graph_v1.pkl` (`v2-2026-08-25`, sha256 `8505108f…`, 노드 160,197 /
  엣지 223,693), 시나리오 17개(seed 42), `--k 4 8 16 --seeds 0 1 2 --repeats 5`.
- 결과 폴더: `benchmarks/results/shortest_path/20260912-161456/` (544행, 전체 925초).
- **아래 값은 이 입력(이 그래프·이 시나리오 데이터셋·이 머신)에서의 관측이며 고정
  기대값이 아니다.** 특히 시간은 머신 상태에 따라 달라지고, popped 중앙값은 해당
  tier×method의 모든 k(4/8/16)·seed(0/1/2) 행을 합쳐 낸 값이라 k를 고정하면 달라진다.

popped 중앙값 (tier × method):

| tier | dijkstra | haversine | random | farthest | planar | avoid |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| near | 2,118 | 312 | 88 | 102 | 102 | 88 |
| mid | 15,137 | 2,844 | 1,768 | 1,658 | 1,384 | 1,501 |
| long | 60,594 | 11,428 | 5,749 | 6,100 | 6,801 | 6,662 |
| detour | 6,450 | 1,250 | 439 | 427 | 426 | 460 |
| same | 1 | 1 | 1 | 1 | 1 | 1 |

`search_median_s` 중앙값(초) (tier × method):

| tier | dijkstra | haversine | random | farthest | planar | avoid |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| near | 0.0072 | 0.0031 | 0.0014 | 0.0011 | 0.0009 | 0.0010 |
| mid | 0.0548 | 0.0301 | 0.0163 | 0.0142 | 0.0092 | 0.0154 |
| long | 0.3146 | 0.1280 | 0.0769 | 0.0643 | 0.0802 | 0.0692 |
| detour | 0.0117 | 0.0122 | 0.0058 | 0.0032 | 0.0033 | 0.0043 |
| same | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |

랜드마크 수(k)를 고정했을 때의 popped 중앙값 — 위 표가 k를 합쳐 낸 값이라 함께 남긴다:

| tier | method | k=4 | k=8 | k=16 |
| --- | --- | ---: | ---: | ---: |
| near | random / farthest / planar / avoid | 154 / 140 / 139 / 136 | 104 / 114 / 114 / 80 | 72 / 64 / 62 / 62 |
| mid | random / farthest / planar / avoid | 2,275 / 2,176 / 1,430 / 2,632 | 1,350 / 1,064 / 1,230 / 1,108 | 874 / 944 / 1,167 / 642 |
| long | random / farthest / planar / avoid | 8,346 / 8,212 / 12,620 / 8,150 | 5,892 / 6,170 / 6,918 / 6,804 | 3,232 / 4,420 / 5,276 / 3,305 |
| detour | random / farthest / planar / avoid | 920 / 480 / 795 / 564 | 418 / 430 / 374 / 486 | 226 / 316 / 370 / 365 |

전처리 비용(이번 실행의 k/seed 조합 전체 합, 초) 과 거리표 크기:

| 방식 | 선정 시간 합 | 거리표 시간 합 | k=4 거리표 | k=8 거리표 | k=16 거리표 |
| --- | ---: | ---: | ---: | ---: | ---: |
| random | 2.9 | 101.1 | 640,788항목 / 8.2MB | 1,281,576 / 16.4MB | 2,563,152 / 32.7MB |
| planar | 4.2 | 33.6 | 〃 | 〃 | 〃 |
| farthest | 107.6 | 87.5 | 〃 | 〃 | 〃 |
| avoid | 326.2 | 77.5 | 〃 | 〃 | 〃 |

- 거리표 크기는 랜드마크 수에만 비례하고 선택법과 무관하다 — 이 그래프는 연결요소가
  1개라 모든 랜드마크가 전체 160,197노드에 도달하기 때문이다(k × 160,197 = 항목 수).
- 선정 시간은 k=16 기준 1회당 random 0.3초, planar 1.6초, farthest 20~24초,
  avoid 57~76초로 관측됐다.
- 정확성: 544행 전부 `status="ok"`, `cost_match` 불일치 0건, `path_valid` 무효 0건.
- Admissibility: 32개 조합 전부 `alt_violations=0`, `haversine_violations=0`
  (조합마다 시나리오 17쌍 검사).
- Planar는 k=4/8/16 모두 `k_actual == k_requested`로, 빈 섹터가 발생하지 않았다.

### 미확인

- `unreachable` tier를 실제 그래프에서 관측하지 못했다(위 "시나리오 설계" 참고). 도달
  불가 탐색이 실제 규모에서 얼마나 걸리는지는 측정되지 않았다.
- 시나리오는 seed 42로 뽑은 17쌍뿐이다. 쌍이 바뀌면 수치도 바뀐다 — 표본이 tier당
  4쌍이라 tier 안의 분산을 논할 수 있는 크기가 아니다.
- 전처리 시간·탐색 시간은 이 머신에서 1회 측정한 값이고, 러너는 반복 간 변동(CV)을
  따로 판정하지 않는다. `search_max_s`로만 흔들림을 짐작할 수 있다.
- 휴리스틱 함수 자체의 호출 비용(Haversine은 노드마다 삼각함수, ALT는 랜드마크 수만큼
  dict 조회)은 따로 분리해 재지 않았다. 탐색 시간 안에 섞여 있어, popped가 줄었는데
  시간이 그만큼 줄지 않는 구간의 원인을 이 데이터만으로는 가를 수 없다.
- 이 실행은 커밋되지 않은 작업 트리에서 돌렸다(`results.metadata.json`의 `dirty=true`).
  같은 수치를 재현하려면 이 절을 담은 커밋을 체크아웃한 뒤 다시 돌려야 한다.
- 랜드마크를 프로덕션 경로에서 준비·보관하는 비용(메모리 상주, 그래프 갱신 시 재계산,
  artifact에 함께 실을지)은 이 벤치마크의 범위 밖이다.
- 어느 구성을 채택할지는 아직 정하지 않았다.

## ALT 서비스 연결 (2026-09-12)

최단거리(`oneway_shortest`) A*의 휴리스틱을 Haversine에서 ALT(Planar, k=8)로 바꿔 연결했다.
랜드마크 선택법과 k를 어떻게 정했는지는
[ALT 랜드마크 선택법·k 선정 근거](../../analysis/route_engine/alt_landmark_selection_validation.md)에
있고, 이 절은 "지금 코드가 무엇을 하는가"만 적는다.

### 책임

서버 기동 때 랜드마크를 고르고 거리표를 메모리에 만들어, 최단거리 A*가 쓸 휴리스틱을
그래프에 붙여 둔다. 준비에 실패하면 조용히 Haversine으로 돌아간다.

### 입력·출력

- 입력: 런타임 그래프 `G`와 설정 4개.

  | 설정 키 | 기본값 | 의미 |
  |---|---|---|
  | `WALK_ALT_ENABLED` | `true` | 끄면 Haversine만 쓴다(되돌리기 스위치) |
  | `WALK_ALT_METHOD` | `planar` | `planar` \| `random`. Farthest·Avoid는 지원하지 않는다 |
  | `WALK_ALT_K` | `8` | 랜드마크 수. Planar에서는 섹터 수 의미 |
  | `WALK_ALT_SEED` | `0` | `random`에만 쓰인다. Planar는 좌표 결정론이라 무시 |

- 출력: `(heuristic, AltRuntimeInfo)` 또는 `(None, None)`. `AltRuntimeInfo`는
  `method`, `k_requested`, `k_actual`, `landmarks`, `select_s`, `table_s`,
  `table_entries`를 담는다.
- 거리표는 **파일로 저장하지 않는다.** 그래프 로드 직후 메모리에 1회 만들고 프로세스
  수명 동안 재사용한다.

### 실행 진입점

| 파일 | 역할 |
|---|---|
| [alt_runtime.py](../../src/route_engine/alt_runtime.py) | `prepare_alt_heuristic()`(선정+거리표), `attach_alt_heuristic()`/`get_alt_heuristic()`(그래프 부착·조회) |
| [dependencies.py](../../src/interfaces/dependencies.py) | `init_route_service()`에서 `precompute_scoring_features(G)` 직후, `RouteService` 생성 **전에** 준비·부착 |
| [oneway_astar.py](../../src/route_engine/engines/oneway_astar.py) | `__init__`에서 쓸 휴리스틱을 정하고 `find_path()`의 `nx.astar_path(heuristic=...)`에 넘긴다 |
| [path_utils.py](../../src/route_engine/engines/path_utils.py) | (2026-09-19 추가) `astar_path()`가 `_search_heuristic()`으로 매 호출 휴리스틱을 고른다 — 순환 경로의 구간 연결이 이 경로를 탄다 |

휴리스틱 선택 규칙 — `OnewayAstarEngine`(위에서부터 먼저 이기는 순서):

1. `OnewayAstarEngine(..., heuristic=...)`로 **명시해서 넘긴 함수** → 로그 `heuristic=alt_injected`
2. 그래프에 부착된 ALT(`G.graph["alt_heuristic"]`) → 로그 `heuristic=alt_planar`
3. 기존 Haversine(`self._heuristic`) → 로그 `heuristic=haversine`

`_heuristic` 메서드는 삭제하지 않고 그대로 남겼다 — 3번 경로가 이것을 쓴다.

휴리스틱 선택 규칙 — `PathUtils.astar_path()`(2026-09-19 추가):

1. `min_ratio >= 1.0`이고 그래프에 ALT가 부착돼 있으면 그 ALT
2. 그 외에는 Haversine 직선거리 × `min_ratio`

`min_ratio < 1.0`에서 ALT를 제외하는 이유는 거리표가 `weight="length"` 기준이기 때문이다.
weight가 항상 `length` 이상이면(거리 그대로, 또는 `cost >= length`인 `WeightedEdgeCost`)
length 기준 하한이 탐색 비용의 하한으로 그대로 성립하지만, `custom_score`처럼 length보다
작아질 수 있는 weight(= `min_cost_length_ratio()`로 구한 `min_ratio < 1.0`)에서는 하한이
실제 비용을 넘어설 수 있어 admissible이 깨진다. 2026-09-19 기준 `min_ratio`를 넘기는
호출자는 없어 실제로는 전부 1번 경로다.

### 의존 영역

`landmark_planar`/`landmark_random`(선정)과 `landmark_shared`(거리표·휴리스틱)에만 의존한다.
`landmark_*` 모듈은 `alt_runtime` 안에서 **지연 import**한다 — 최상단에서 가져오면
`landmark_* → engines.path_utils → engines/__init__ → oneway_astar → alt_runtime`로
순환 import가 닫힌다.

반대 방향인 `path_utils → alt_runtime`(2026-09-19 추가)은 최상단 import로 둬도 순환이
닫히지 않는다 — `alt_runtime`이 최상단에서 가져오는 것은 stdlib과 networkx뿐이고
`src/route_engine/__init__.py`가 비어 있어 `engines` 패키지를 끌어오지 않는다. 지연
import로 두지 않은 이유는 호출 빈도다(순환 경로는 요청 1건에 구간 연결 A*를 반복 호출한다).
확인: `path_utils`·`alt_runtime`·`landmark_planar` 각각을 첫 import로 놓고 셋 다 성공.

### 변경 영향

- **(2026-09-19 갱신) 순환 경로 엔진(`CircularGraspWaypointAlnsEngine`)도 이제 ALT를 쓴다.**
  `PathUtils.astar_path()`가 부착된 ALT를 우선 사용하도록 바뀌면서, 구간 연결 경로
  (`_CostCache.astar_path()` → `PathUtils.astar_path()` → `nx.astar_path`)가 최단거리 A*와
  같은 휴리스틱을 타게 됐다. 가중 비용(`cost >= length`) 아래에서도 admissible이 유지되는
  근거는 위 "비용식과 ALT 재사용 근거" 절과 같다.
  같은 함수를 쓰는 `DistancePathFinder`(Beam 조립), `benchmarks/runner/waypoint_overlap_audit.py`,
  `scripts/waypoint_pipeline_demo.py`도 함께 영향을 받는다 — 셋 다 `length` 이상인 weight라
  최적성은 그대로다.
  ⚠ 벤치마크 워커(`_pool_worker_init()`)는 ALT를 준비·부착하지 않는다. 벤치에서 순환
  경로를 돌리면 여전히 Haversine 폴백으로 측정된다(2026-09-19 기준 미배선 — 배선하지
  않기로 한 근거는 아래 "관측: 순환 경로 구간 연결" 절 참고).
- `WaypointComposerEngine`은 leg를 `OnewayAstarEngine`으로 채우므로 그 leg는 ALT를 쓴다.
  응답 계약은 아래 이유로 달라지지 않는다.
- **응답 계약**: ALT와 Haversine은 둘 다 admissible하므로 A*가 찾는 **최적 비용은 항상
  같다**. `visited_nodes` 페널티가 있어도 마찬가지다 — 그 페널티는 비용을 늘리기만 해서
  (배수 ≥ 1) 페널티 없는 거리로 만든 ALT 하한이 여전히 실제 비용 이하다.
  ⚠ 다만 **최단경로가 여럿이면(동점) 어느 것을 고르는지는 달라질 수 있다.** 2026-09-12
  확인: 간선 길이가 전부 같은 toy grid에서는 두 휴리스틱이 비용은 같고 노드열이 다른
  경로를 냈고, 길이를 서로 다르게 해 동점을 없애면 노드열까지 같아졌다. 실제 서울
  도보망은 `length`가 실수값이라 동점이 드물고, 아래 확인에서도 좌표가 완전히 같았다.
- **메모리**: 거리표가 k=8 기준 약 16MB(128만 항목) 상주한다. `G.graph`에는 dict가 아니라
  **함수 객체만** 올려서 `visualizations/route_experiment.py`의 `copy.deepcopy(graph)`가
  표를 복제하지 않는다(`copy.deepcopy`는 함수를 원자값으로 취급한다).
- ⚠ 휴리스틱이 붙은 그래프는 **pickle되지 않는다**(로컬 클로저). 그래프를 pickle하는
  `GraphArtifactRepository.save()`의 호출자는 새로 만든 그래프만 저장하므로 현재는
  문제가 없다. 런타임 그래프를 pickle하는 코드가 생기면 이 제약을 먼저 확인할 것.

### 실패·복구

- **되돌리기**: `.env`에 `WALK_ALT_ENABLED=false`를 넣고 재기동한다. 코드 변경 없이
  기존 Haversine 동작으로 완전히 돌아간다.
- **자동 폴백**: 랜드마크 선정이나 거리표 생성이 어떤 이유로든 실패하면
  `prepare_alt_heuristic`이 예외 종류·메시지를 warning 로그로 남기고 `(None, None)`을
  돌려준다. 그래프에는 아무것도 붙지 않고 엔진이 Haversine을 쓴다 — **기동은 막히지
  않는다.** 지원하지 않는 `method`만 `ValueError`로 올린다(설정 오타를 조용히 넘기면 안
  되기 때문이며, `Literal` 타입이라 pydantic이 먼저 막는다).
- 기동 로그에서 `ALT 휴리스틱 준비 완료: method=... k_actual=... 선정 ...s 거리표 ...s`를
  확인한다. 이 줄이 없고 warning만 있으면 폴백된 것이다.

### 검증

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_alt_runtime.py tests/unit/test_oneway_astar_alt.py -q
./.venv/Scripts/python.exe -m pytest tests/unit -q --ignore=tests/unit/test_oneway_random.py
./.venv/Scripts/python.exe -m pytest visualizations/tests -q --basetemp outputs/algorithm_visualization/tests
```

- 2026-09-12: 신규 28개 통과(`test_alt_runtime.py` 14개, `test_oneway_astar_alt.py` 14개).
  `tests/unit` 전체는 600 통과, `visualizations/tests`는 52 통과 1 skip.
  `tests/unit`에 남은 실패·에러 57건은 전부 이 변경 전(HEAD)에서도 같게 실패하는
  기존 항목이다(인증·배너·수집기·graph repository 등, 별도 worktree에서 HEAD와 대조).
- `tests/integration/test_api.py`: 2026-09-12 실행 결과 28개 통과, 6개 실패. 실패 6건은 전부 인증
  토큰 테스트이고 원인이 이 변경과 무관한 기존 드리프트다
  (`AuthService.get_access_token() missing 1 required positional argument: 'provider_id'`,
  `check_access_token` mock이 2-튜플을 돌려주는데 호출부는 3개를 푼다).
  `POST /api/walk/route` 관련 테스트는 통과했다.

### 관측: 연결 후 실제 호출 (2026-09-12)

환경: Windows-11, Python 3.12.14, networkx 3.6.
입력: `artifacts/walk_graph_v1.pkl`(`v2-2026-08-25`, 노드 160,197 / 엣지 223,693),
시나리오는 `benchmarks/datasets/shortest_path.json`의 `near-1`·`long-1`·`same-1`.
**이 입력·이 머신에서의 관측이며 고정 기대값이 아니다.**

기동 시 ALT 준비(2회 관측): 선정 1.02~1.24초, 거리표 6.75~6.92초, **합계 7.9~8.0초**.
`k_actual=8`(요청 8개 전부 확보, 빈 섹터 없음), 거리표 항목 1,281,576개.

`WALK_ALT_ENABLED` on/off 응답 비교(`RouteService.get_route`, `oneway_shortest`, 각 3회):

| 시나리오 | status | total_km | 좌표 수 | on/off 응답 동일 | 3회 반복 일관 |
|---|---|---:|---:|---|---|
| `near-1` | success | 1.77 | 40 | 예 | 예 |
| `long-1` | success | 10.36 | 173 | 예 | 예 |
| `same-1` | success | 0.00 | 1 | 예 | 예 |

`status`·`total_km`·좌표열이 모두 완전히 같았고, 노드열(`last_path_nodes`)까지 같았다.
기동 로그에서 부착 시 `heuristic=alt_planar`, 떼면 `heuristic=haversine`이 찍히는 것도
확인했다.

탐색 자체의 시간(엔진 `nx.astar_path` 호출만, 5회 중 최소):

| 시나리오 | ALT | Haversine | 배속 |
|---|---:|---:|---:|
| `near-1` | 0.0006s | 0.0022s | 3.73x |
| `long-1` | 0.0166s | 0.0628s | 3.79x |
| `same-1` | 0.0000s | 0.0000s | 1.04x |

⚠ **그런데 요청 전체 시간에서 탐색이 차지하는 비중이 작다.** `OnewayAstarEngine.run()`은
매 호출마다 `compute_distance_only_lookup(G, blocked_tags)`로 전체 엣지의 weight 조회표를
다시 만드는데, 같은 환경에서 이 한 번이 **0.408초**였다. ALT가 아낀 절대 시간은
`near-1` 0.0016초, `long-1` 0.046초로 그 조회표 1회 비용의 0.4%·11.3%에 그친다.
실제로 `same-1`(탐색이 즉시 끝나는 경우)의 `run()`도 1.5초 넘게 걸렸다. 즉 **탐색은
3.7배 빨라졌지만 요청 한 건의 체감 시간은 그만큼 줄지 않는다** — 병목이 탐색 밖에 있다.
이 조회표 비용을 줄이는 것은 이 작업의 범위가 아니라 별도 과제다.

### 관측: 순환 경로 구간 연결 (2026-09-19, #465)

환경: Windows-11, Python 3.12.10(`poetry run python`), networkx 3.6.
입력: `benchmarks/fixtures/`(노드 160,328 / 엣지 223,927), 시나리오는
`benchmarks/datasets/route_engine.json`의 `circular_01`~`circular_08`(목표 2.5~4.9km),
엔진은 `CircularGraspWaypointAlnsEngine`(N=4, 기본 시드).
재현: `python -m benchmarks.run_alt_circular_validation`.
**이 입력·이 머신에서의 관측이며 고정 기대값이 아니다.**

| 지표 | Haversine | ALT | 비 |
|---|---:|---:|---:|
| 구간 연결 A* 호출 | 854 | 854 | 동일 |
| popped(큐에서 꺼낸 노드) | 77,994 | 43,993 | 1.77x 감소 |
| pushed | 101,498 | 65,071 | 1.56x 감소 |
| A* 순수 시간 | 0.25s | 0.22s | 1.11x |
| 요청 전체 시간(8건 합) | 33.32s | 28.10s | — |
| A*가 전체에서 차지하는 비중 | 0.7% | 0.8% | — |

- **결과는 완전히 같다.** 노드열 8/8 일치, 거리 최대 차이 0.000000m. A* 호출 수도 8건
  모두 같아 `_CostCache`의 캐시 동작이 휴리스틱 교체에 영향받지 않는 것도 확인됐다.
- **탐색량은 실제로 1.77배 줄었다.** `popped`는 결정론적 값이라 2회 실행에서 같은 수가
  나왔다(시간은 실행마다 흔들린다). 시나리오별로는 1.07x~2.15x다.
- ⚠ **그런데 시간은 1.11배만 줄었고, 그 A*가 요청 전체의 1% 미만이다.** 노드를 1.77배
  덜 펼쳤는데 시간이 그만큼 안 준 것은 노드당 휴리스틱 비용이 ALT 쪽이 비싸기
  때문이다(랜드마크 k=8개 표 조회 대 삼각함수 1회). 게다가 순환 요청 시간의 99%는
  경유지 풀 생성과 ALNS 반복이라, 구간 연결 A*를 아무리 개선해도 체감으로 이어지지
  않는다. 이 변경의 근거는 속도가 아니라 **결과 불변 + 최단거리 A*와의 휴리스틱
  일관성**으로 읽어야 한다.
- 위 시나리오 8건의 전체 시간 차이(33.32s 대 28.10s)는 A* 시간 차이(0.03s)로 설명되지
  않는다 — 실행 간 머신 편차다. 시간이 아니라 `popped`를 비교 기준으로 삼아야 하는
  이유이기도 하다.
- 벤치마크 워커(`_pool_worker_init()`)에는 ALT를 배선하지 않았다. 워커마다 준비
  시간(이 실행에서 3.10초)이 붙는데 측정 대상이 요청 시간의 1% 미만이라 얻는 정보가
  없다고 판단했다(2026-09-19). 필요해지면 `90bf83d`(가중 비용)와 같은 방식으로 넣는다.

### 관측: 순환 경로 구간 연결 × 가중 비용 (2026-09-20, #476)

환경: Windows-11, Python 3.12.10(`poetry run python`), networkx 3.6.
입력: `artifacts/walk_graph_v1.pkl`(`v3-2026-09-19`, 노드 160,197 / 엣지 223,693), 시나리오는
위와 같은 `circular_01`~`circular_08`, 엔진은 `CircularGraspWaypointAlnsEngine`(N=4).
선호도: `safety=0.4`, `comfort=0.3`(`WALK_WEIGHT_LIMIT` 기본값 0.7과 합이 같아
`normalize_preference_weights()`의 축소 없이 그대로 반영됨).
재현: `python -m benchmarks.run_alt_circular_validation`(#476에서 가중 비용 비교 블록 추가 —
거리 전용 블록은 위 2026-09-19 관측과 동일한 코드다).

| 지표 | 거리 전용 | 가중 비용 |
|---|---:|---:|
| 노드열 완전 일치(Haversine=ALT) | 8/8 | 8/8 |
| 거리 최대 차이 | 0.000000m | 0.000000m |
| popped 감소(Haversine/ALT) | 1.78x | 1.39x |
| A* 시간 단축(Haversine/ALT) | 1.19x | 1.07x |
| A*가 전체에서 차지하는 비중(Haversine/ALT) | 0.8%/0.7% | 1.5%/1.4% |

**이 입력·이 머신에서의 관측이며 고정 기대값이 아니다.**

- **가중 비용을 켜도 ALT는 여전히 정확하다.** 8개 시나리오 모두 Haversine과 노드열이
  완전히 같고 거리 차이는 0이다 — `WeightedEdgeCost`가 페널티 전용 모델(`cost >= length`)
  이라 `weight="length"`로 만든 ALT 거리표가 가중 비용 아래서도 하한으로 유효하다는 설계
  불변식(`scoring_engine.py::WeightedEdgeCost` docstring)이 실그래프에서 확인됐다.
- **다만 ALT의 탐색량 절감 효과는 가중 비용 아래서 더 작다**(popped 1.78x → 1.39x, A*시간
  1.19x → 1.07x). `length` 기준으로만 만든 ALT 랜드마크 하한이, 엣지마다 `unsafe`/
  `discomfort`가 더해져 울퉁불퉁해진 실제 비용을 상대적으로 덜 타이트하게 근사하는
  것으로 보인다 — "ALT가 항상 1.78배 줄여준다"로 일반화하면 안 된다.
- **가중 비용 자체가 경로에 실제로 영향을 준다.** 8개 시나리오 전부 거리 전용과 다른
  경로가 나왔다(가중 비용 적용 후 경로가 달라진 시나리오: 8/8) — cost_context 배선이
  실그래프 A*에 실제로 반영되는 것을 확인했다.
- A*비중이 거리 전용(0.7~0.8%) 대비 가중 비용(1.4~1.5%)에서 거의 2배다 — 엣지마다
  `_score()`가 두 속성(safety/slope)을 읽고 median 대체 여부를 판단하는 비용이 Haversine/
  ALT 휴리스틱 계산보다 크기 때문이다. 그래도 전체 요청 시간의 2% 미만이라 "탐색 개선이
  체감으로 이어지지 않는다"는 2026-09-19 관측의 결론은 가중 비용 아래서도 유지된다.

### 관측: GRASP+ALNS 가중치 3점 검증 (2026-09-20, #495)

환경: Windows-11, Python 3.12.10(`poetry run python`), networkx 3.6.
입력: `artifacts/walk_graph_v1.pkl`(`v3-2026-09-19`, 노드 160,197 / 엣지 223,693), 최대
연결요소의 최소 id를 시작점으로 고정, `target_km=3.0`, 서비스 확정 엔진
`grasp-wp-alns`(`CircularGraspWaypointAlnsEngine`) 단독.
재현: `python -m benchmarks.run_grasp_alns_weighted_check --n-baseline 120 --n-weighted 120`.
`--safety`/`--comfort` 입력값 기준 세 지점(0/0, 0.25/0.15, 0.45/0.3)에서 각 120회(seed
0~119)씩, 총 360회 순차 실행(`run_benchmark()`의 멀티프로세스 격리 없이 `solver.solve()`
직접 반복 호출 — "서로 다른 경로 수" 집계에 필요한 raw 노드열을 얻기 위함, 위 문단들과
측정 방식이 다르다).

| 지점 | alpha/beta(유효값) | 게이트 통과율 | elapsed_sec(평균/p95/최악) | 거리편차 평균 | 재통행 평균 | 서로 다른 경로 수 |
|---|---|---:|---:|---:|---:|---:|
| baseline | 0.0/0.0 | 120/120 | 1.57/2.18/2.74s | 0.020km | 0.0188 | 25/120 |
| mid | 0.25/0.15 | 120/120 | 2.03/2.86/3.28s | 0.026km | 0.0173 | 24/120 |
| upper | 0.45/0.3 → 0.42/0.28(비례 축소) | 120/120 | 2.54/3.86/5.98s | 0.028km | 0.0105 | 24/120 |

**이 입력·이 머신에서의 관측이며 고정 기대값이 아니다.**

- **세 지점 모두 이슈가 정한 "되돌아갈 기준"을 통과해 설정값(`alns_candidate_limit` 등)
  조정은 하지 않기로 했다.** 서로 다른 경로 수(5개 미만이면 조정)는 24~25/120로 여유가
  있고, 게이트 통과율(61/72 대비 유의한 하락이면 보정)은 세 지점 다 100%로 하락이 없다.
  동시 3건 최악값 40초 초과 기준도 개별 worst 2.7~6.0초로 크게 못 미친다 — 다만 이
  실행은 순차 단일 프로세스라 "동시 3건"이 뜻하는 동시성 부하 자체를 잰 것은 아니다.
- **`upper` 지점에서 `normalize_preference_weights()`의 비례 축소가 실측으로 확인됐다.**
  `safety+comfort=0.75`가 `WALK_WEIGHT_LIMIT`(0.7)을 넘어 실제 `alpha/beta`는
  `0.42/0.28`로 줄어든 채 CSV에 기록됐다 — "선호도 입력값과 alpha/beta는 다르다"(위
  #445 절 참고)는 설계 그대로다.
- **1회짜리 관측은 신뢰할 수 없다는 것도 이번에 확인됐다.** 본 실행 전 지점당 1회만 돈
  스모크에서는 elapsed_sec이 1.46→1.69→3.37s로 가중치와 함께 느는 것처럼 보였는데,
  지점당 15회 이상으로 늘리자 그 추세가 사라졌다(3.52→3.14→2.67s, 오히려 감소) —
  단일 seed 비교로 시간 추세를 판단하면 안 된다.
- **회귀 비교(이슈 To-Do 1번, "alpha=beta=0 회귀 — 기존 CSV와 완전 일치 확인")는 수행하지
  않았다.** 저장소에 남아 있던 grasp-alns 관련 CSV(`alns_sweep_results.csv` 등, 전부
  2026-09-11~16 생성)는 모두 #474(그래프 원본을 artifact 하나로 통일) 이전, 즉 별도
  parquet fixture(160,328노드/223,927엣지)로 만든 결과라 지금 쓰는 통일된 artifact와
  노드 ID 자체가 달라 완전 일치 비교 대상이 될 수 없었다. 이번 baseline 120회 결과가
  #474 이후 첫 기준선이므로, 다음번 관련 코드 변경 뒤에는 이 CSV(`benchmarks/results/
  grasp_alns_weighted_check_raw.csv`, git 미추적)와 비교하면 된다.

### 미확인

- **실제 서버를 띄워 HTTP로 확인하지는 못했다.** Docker/PostgreSQL이 떠 있지 않아
  `src.main`의 lifespan(`init_db()`)을 통과하는 기동을 할 수 없었다. 위 on/off 비교는
  `RouteService`를 직접 만들고 인증을 스텁으로 대체해서 잰 것이다.
  `tests/integration/test_api.py`의 `POST /api/walk/route` 테스트는 통과하지만 그 테스트는
  `route_service`를 mock으로 갈아끼우므로 ALT 경로를 타지 않는다 — 즉 **라우터·쿠키 인증을
  통과해 ALT가 실제로 쓰이는 경로는 아직 확인되지 않았다.**
- **PostgreSQL을 그래프 소스로 쓸 때**(`WALK_GRAPH_SOURCE=database`)의 기동 시간은
  측정하지 않았다. 위 수치는 artifact 로드 기준이다.
- **거리표 파일 저장은 구현하지 않았다.** 기동 때마다 다시 만든다. 콜드 스타트가 잦은
  환경(Cloud Run 등)은 이 구조의 전제 밖이다.
- 동시 요청 부하에서의 메모리·지연은 재지 않았다. 거리표는 읽기 전용이라 요청 간
  공유되지만, 실측하지는 않았다.
- 경유지(`waypoint`) 모드에서 leg마다 ALT를 쓸 때의 전체 응답 시간 변화는 재지 않았다.

## Waypoint(경유지) 조합 엔진

- `waypoint.py`(`WaypointComposerEngine`)는 출발지 → 경유지들 → 목적지를 구간(leg)별로 나눠, 각 leg에 지정된 모드의 편도 엔진을 순차 호출해 하나의 경로로 이어 붙인다. 새 탐색 알고리즘은 추가하지 않고 기존 엔진을 조합만 한다. (2026-09-19 갱신) `_LEG_ENGINES`의 세 키(`oneway_shortest`/`oneway_random`/`oneway_preferred`)가 지금은 전부 `OnewayAstarEngine`이다 — `OnewayBeamEngine`은 삭제됐고, `oneway_random`이 임시로 `oneway_shortest`와 같은 엔진을 쓰는 동안은 셋 다 사실상 같은 동작이다(다만 나중에 갈라칠 수 있도록 분기는 합치지 않고 남겨 뒀다).
- 입력은 `WaypointRouteInput`(`src/schema/route_schema.py`)이며 `waypoints`(경유지 좌표 리스트), `leg_modes`(leg별 모드), `leg_target_km`(leg별 목표 거리, `oneway_random` leg만 필수)로 구성된다. `len(leg_modes) == len(waypoints) + 1`이어야 한다.
- `leg_modes`/`leg_target_km`은 `WalkMode`/`Coordinate`를 그대로 쓰지 않고 `route_schema.py` 안에 로컬로 정의한 `WaypointLegMode`와 `WaypointCoordinate`를 쓴다. (2026-09-19 갱신) `WaypointLegMode`는 지금 `Literal["oneway_shortest", "oneway_random", "oneway_preferred"]`(3개 값, #445에서 `oneway_preferred` 추가)다. 로컬 재정의 이유로 적혀 있던 `route_schema.py -> walk_schema.py -> route_engine.profiles -> route_schema.py` 순환 임포트는 더 이상 사실이 아니다 — `profiles.py`가 삭제되면서 그 순환 고리 자체가 없어졌고, 실제로 지금 `route_schema.py`는 `src.*` 모듈을 전혀 import하지 않는다(`typing`/`pydantic`만 사용). 그래도 `walk_schema.py`는 여전히 import하지 않는데, 이는 `route_schema.py`가 route_engine 계층 스키마로서 API/챗봇 계층 스키마(`walk_schema.py`)에 의존하지 않는 편이 계층 경계상 낫다는 판단으로 남아 있는 것으로 보인다(재검증 필요 — 원래의 순환 임포트 근거는 더 이상 유효하지 않다).
- `WaypointComposerEngine`은 그래프를 직접 mutate하지 않고 leg 엔진에 그대로 넘기기만 하므로 `G.copy()`를 하지 않는다(`self.G = G`). 실제 mutation은 그걸 하는 leg 엔진이 자체적으로 격리한다. 인접 leg의 경계 좌표는 동일한 `(lat, lon)` 값을 그대로 재사용해 노드 스냅 불일치를 방지한다.
- leg가 실패하면(그리고 아직 `oneway_shortest`로 시도하지 않았다면) `OnewayAstarEngine`으로 그 leg만 재시도한다(다른 엔진들의 `base_shortest` 대체와 같은 패턴). 그 재시도까지 실패해야 해당 leg에서 중단한다.
- 결과 상태(`_stitch`)는 모든 leg 성공 시 `SUCCESS`, 일부만 성공 시 `PARTIAL_ROUTE`(성공한 구간까지만 좌표·거리 반환), 첫 leg부터(재시도 포함) 실패하면 그 leg의 실패 status를 그대로 사용한다. `mode`는 이 조합 전용으로 추가한 `WalkMode.WAYPOINT`를 쓴다.
- `route_service.py`와 연동됐다(2026-08-07): `RouteService.base_engines[WalkMode.WAYPOINT] = WaypointComposerEngine`, `_build_engine()`이 `waypoints`/`leg_modes`/`leg_target_km`를 받아 `WaypointRouteInput`을 구성한다. LLM이나 API 호출자가 일부 leg만 지정해도 나머지는 `oneway_shortest`로 자동 패딩해 `len(leg_modes) == len(waypoints)+1` 불변식을 채운다. 각 waypoint 좌표도 origin/destination과 동일하게 `find_nearest_node_with_expansion` 사전 검증을 거친다.
- `walk_router.py`(직접 REST API)에는 아직 연동하지 않았다 — GPS Art와 마찬가지로 챗봇 경유만 지원한다.
- 챗봇 연동: `mode_tools.py`에 `select_waypoint`(`origin`/`waypoints`/`destination`/`legs` → `WayPointPreference`)가 추가됐고, `route_tools.py`에 `waypoint_route` tool이, `route_executor.py`의 `MODE_TOOL_MAP`에 `WalkMode.WAYPOINT: "waypoint_route"`가 추가됐다. `RouteExecutor.run`은 `WayPointPreference.legs`(`{mode, target_km}` 객체 리스트)를 `leg_modes`/`leg_target_km` 두 리스트로 분리해 tool 인자를 구성한다. 경유지 장소 검색은 `place_tools.py`의 `target="waypoint"`+`waypoint_index`로 식별하고, `interviewer.py`가 인덱스별 후보(`state.waypoint_candidates`)를 관리한다.
- leg별 `profile`/`custom_weights` 지정은 여전히 지원하지 않는다 — `RouteExecutor`가 계산한 공통 `profile`/`custom_weights` 하나를 `WaypointComposerEngine` 생성자를 통해 모든 leg에 동일하게 적용한다(변경 없음).
- `extraction.yaml`에 `select_waypoint` 선택 규칙(경유지 표현 판단, 순환 코스 처리, `waypoints`/`legs` 필드 추출, 판단 예시 3개)이, `interview.yaml`에 경유지 장소 검색 가이드(`target="waypoint"`+`waypoint_index` 지정, 인덱스 오검색 방지, 복수 경유지 확인 질문)가 추가됐다(2026-08-07).
- **아직 확인 안 된 것**: 위 prompt 가이드가 추가됐다는 것과 실제 LLM이 대화에서 이 모드를 의도대로 선택·태깅한다는 것은 다른 문제다 — 정적 대조(YAML 파싱, `load_prompt(...).format(...)` 렌더링 확인)만 했고 실제 LLM 호출로 검증하지 않았다. 이 연동은 `tests/unit/test_routue_service.py::TestWaypointRouting`(mock 엔진 기반 4개 테스트) + 기존 `test_waypoint_engine.py`(엔진 자체 단위 테스트)로만 확인했고, 실제 그래프·LLM·Kakao를 사용한 실행 검증은 하지 않았다.

**leg 간 경로 겹침 방지(visited_nodes 페널티)**

(2026-09-19 갱신) `OnewayBeamEngine`은 삭제됐다 — 아래는 지금 leg 엔진으로 남은
`OnewayAstarEngine`의 동작만 설명한다.

- `OnewayAstarEngine`은 선택적 생성자 파라미터 `visited_nodes: Optional[set] = None`을 받는다. 기본값(미지정, 빈 set)이면 기존 동작과 완전히 동일하다 — `route_service.py`가 단독으로 쓰는 일반 편도 요청에는 영향이 없다.
- `WaypointComposerEngine.run()`은 leg마다 성공한 경로의 노드열을 `visited_nodes` 집합에 누적하고, 다음 leg의 엔진(재시도 포함)에 그 집합을 전달한다. `_RETURN_REVISIT_PENALTY`(5배)로, 도착지 자신을 제외한 기방문 노드로 가는 엣지 가중치에 페널티를 곱해 우회를 유도한다.
- `OnewayAstarEngine`은 `find_path()`가 최적화하는 가중치 함수 자체에 페널티가 들어가므로, 페널티가 있으면 순수 최단경로가 아니라 "기방문 노드를 피하는 최단경로"를 반환한다 — leg 라벨이 `oneway_shortest`여도 마찬가지다.
- `last_path_nodes` 속성이 있다 — 가장 최근 `run()`이 실제로 사용한 노드열이며, `WaypointComposerEngine`이 다음 leg의 `visited_nodes`를 누적할 때 이 값을 읽는다.
- `GpsArtEngine`은 내부적으로 `WaypointComposerEngine`을 그대로 쓰므로 별도 수정 없이 이 겹침 방지 로직을 그대로 물려받는다 — 도형이 스스로 교차하는 경우 겹치는 구간을 우회하려고 시도한다(단, 가중치 함수에 반영될 뿐 최종 결과가 반드시 우회로가 되는 것은 보장하지 않는다).

## GPS Art

경유지 반영 경로를 응용해, 도형 모양대로 걷는 경로를 생성한다. route_engine 계산(`GpsArtEngine`)과 이미지 생성·윤곽선 추출(`GpsArtService`, `src/service/route/gps_art_service.py`) 두 layer로 나뉜다.

**`GpsArtEngine`(`gps_art.py`, route_engine 계산)**

- 입력은 `GpsArtRouteInput`(`src/schema/route_schema.py`): `shape_points`(정규화된 도형 좌표, 로컬 단위·단위 없음), `origin_lat`/`origin_lon`(배치할 중심 위경도), `target_km`(목표 총 이동 거리). `shape_points`는 검증 시점에 첫 점=마지막 점이 되도록 자동으로 닫힌다.
- `_map_to_geo`: `shape_points`를 실제 위경도로 변환한다. 도형의 로컬 단위 둘레와 `target_km`(도로망 계수 1.4로 나눠 직선 기준으로 역산)의 비율로 scale을 구하므로, 입력 좌표가 어떤 절대 크기·단위든 상관없이 항상 `target_km`에 맞게 배치된다(스케일 불변).
- `_snap_to_nodes`: 변환된 위경도를 그래프 최근접 노드로 스냅한다. 연속으로 같은 노드에 스냅되면(도로망이 성긴 구간) 하나로 합친다.
- 스냅된 노드열을 `WaypointRouteInput`으로 변환해 `WaypointComposerEngine`에 위임한다. 도형 왜곡을 막기 위해 모든 leg를 `oneway_shortest`로 고정하고, `custom_weights`로 모든 가중치를 0으로 채운 `_DISTANCE_ONLY_WEIGHTS`를 명시적으로 넘긴다(2026-08-07 수정). (2026-09-19 갱신) `_DISTANCE_ONLY_WEIGHTS = Weights(safety=0.0, comfort=0.0)`다 — `get_profile()`/`ScoringProfile`(옛 profile 시스템)은 삭제됐다. `WaypointComposerEngine(waypoint_inp, self.G)`처럼 `custom_weights`를 아예 안 넘기면 `Weights()`의 기본값(`safety=0.5`, 전혀 중립이 아니다)이 쓰여 안전 점수 좋은 엣지를 실제보다 "더 짧게" 취급해 도형이 그쪽으로 휘어질 수 있다 — 그래서 명시적으로 둘 다 0으로 채운다.
- `WaypointComposerEngine`과 마찬가지로 그래프를 mutate하지 않아 `G.copy()`를 하지 않는다.
- 최종 응답의 `mode`는 `WaypointComposerEngine`이 채우는 `WAYPOINT`를 `GPS_ART`로 덮어써서 반환한다.

**`GpsArtService`(`src/service/route/gps_art_service.py`, 이미지→좌표 준비)**

- `get_shape_points(access_token, shape_name)`(async): 인증 확인 → `pictures/{shape_name}.png` 캐시 확인(있으면 재사용, 없으면 `GPTClient.generate_image()`로 생성 후 저장) → OpenCV로 배경 제거·윤곽선 추출 → `List[GpsArtPoint]`(정규화된 도형 좌표, 위경도 아님) 반환.
- 윤곽선 단순화는 균등 간격 샘플링이 아니라 `cv2.approxPolyDP`(Douglas-Peucker)를 쓴다 — 직선 구간은 점 간격과 무관하게 양 끝점만 남고, 곡선은 굴곡에 따라 필요한 만큼만 점이 남는다.
- 반환값의 절대 스케일은 정규화(원점 이동·y축 반전만 함)하지 않는다 — `GpsArtEngine._map_to_geo`가 어차피 `target_km` 비율로 다시 계산하기 때문에 여기서 크기를 맞출 필요가 없다.
- 이 서비스는 `route_engine`과 달리 외부 API(OpenAI Images API)를 직접 호출한다 — `GpsArtEngine`(route_engine)은 여전히 이 경계를 지킨다.
- 이미지 생성 프롬프트는 `src/prompt/gps_art_image.yaml`(스타일 고정: 흰 배경·굵은 검은 실루엣·장식 없음). 런타임에서 `cv2`(`opencv-python`)를 실제로 쓰므로 `pyproject.toml`/`requirements.txt`에 의존성으로 선언돼 있다.

**챗봇 연동(2026-08-06)**

- `ModeTool.select_gps_art`(`src/agent/tools/mode_tools.py`)는 `origin`·`shape`(도형 이름 문자열)·`target_km`만으로 `GPSArtPreference`를 만든다. 이미지 생성·좌표 추출은 이 시점에 하지 않는다 — `ModeTool`(추출)과 `RouteTool`+`RouteExecutor`(실행)가 나뉜 기존 패턴을 그대로 따른다.
- 확인(confirmation) 이후 `RouteExecutor`가 `RouteTool.gps_art_route`(`src/agent/tools/route_tools.py`)를 호출하면, 그 안에서 `GpsArtService.get_shape_points(access_token, shape)`(이미지 생성+윤곽선 추출)를 먼저 `await`하고, 그 결과 `shape_points`를 `RouteService.get_route(..., shape_points=...)`에 그대로 넘긴다. `RouteService.get_route`/`_build_engine`은 동기 함수로 남고, 이미 좌표 변환이 끝난 값만 받는다(`route_service.py`).
- `RouteService.base_engines`에 `WalkMode.GPS_ART: GpsArtEngine`이 추가됐고 `_build_engine`에 GPS_ART 분기가 생겼다. `GpsArtEngine`은 `custom_weights`/`profile`을 받지 않지만(leg가 전부 `oneway_shortest` 고정), `RouteExecutor`가 모드와 무관하게 항상 `args["profile"]`/`args["custom_weights"]`를 채워 넘기므로 `gps_art_route` tool 시그니처는 다른 3개 tool과 동일하게 두 파라미터를 받되 내부에서는 쓰지 않고 버린다.
- `Extractor.run`은 `pref.mode == WalkMode.GPS_ART`일 때 `_extract_themes`(themes.yaml LLM 호출)를 건너뛰고 `state.themes = []`로 둔다 — `GpsArtEngine`이 테마 기반 가중치를 쓰지 않아 결과에 반영되지 않는 LLM 호출이기 때문이다(`extractor.py`).
- `Interviewer._is_complete`/`_get_missing_info`가 `GPSArtPreference`를 인식해 `origin`·`target_km`뿐 아니라 `shape`도 필수로 체크한다(`interviewer.py`). 확인 질문은 2026-08-20부터 하드코딩 문구 없이 `interview.yaml`이 `current_context`(shape 포함)를 보고 생성한다.
- `GpsArtService`는 `src/interfaces/dependencies.py`에 다른 서비스와 같은 싱글톤 패턴(`gps_art_service`, `get_gps_art_service()`)으로 추가됐고, `RouteExecutor.__init__`이 이 getter로 받아 `RouteTool(gps_art_service)`에 주입한다.

- `src/prompt/extraction.yaml`에 `select_gps_art` 선택 규칙(구체적 도형 이름이 있을 때만 선택, "예쁜 길"류 분위기 묘사와 구분)과 `shape` 필드 추출 규칙, 판단 예시 3개가 추가됐다(2026-08-06).

**아직 확인 안 된 것**: 그래프 로드·GPT 이미지 생성·PostgreSQL이 필요해 이 변경은 정적 대조와 문법 체크(YAML 파싱 포함)만 마쳤고 실제 실행 검증은 아직 안 했다. 전용 단위·통합 테스트도 없다 — `extraction.yaml`의 새 규칙이 실제 LLM 호출에서 의도대로 GPS Art를 선택·오선택하지 않는지도 아직 확인 전이다. `walk_router.py`(직접 REST API)가 쓰는 `WalkRouteRequest`에는 `shape` 필드가 없어 GPS Art를 직접 호출할 수 없는데, `walk_router.py`는 레거시로 간주해 연동 대상에서 제외했다 — 챗봇 경유만 지원한다.

## 영역 경계

- 외부 API와 LLM을 직접 호출하지 않습니다.
- HTTP 요청·응답을 처리하지 않습니다.
- 데이터 원본을 직접 적재하지 않습니다.
- 입력 Graph와 Weights(선호도)를 받아 경로 계산 결과를 반환합니다.

## V1 점수 방향

(2026-09-19 갱신) 8축→2축(safety/comfort) 축소로 이 절이 설명하던 다축 프로필 모델
(`convenient`/`accessible` 프로필, `blocked_tags`, `child_score`/`is_vehicle_caution` 등)은
전부 삭제됐다 — 지금 실제로 쓰이는 점수 방향·결측 처리는 [graph_contract.md](graph_contract.md)의
"안전·편안 Score의 방향과 결측" 절이 단일 기준이다(`safety_score`↑=안전, `accident_score`↑=위험,
`slope_score`↑=평탄, NULL과 `0.0`을 구분). 같은 계약을 여기 다시 적지 않는다. 옛 다축 모델의
전체 내용은 git 이력에서 확인한다.
