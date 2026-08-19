# 경로 생성 엔진

> 상태: Current
> 기준일: 2026-08-08
> 관련 코드: `src/route_engine/`

경로 생성 엔진은 외부 API나 챗봇 처리와 분리된 경로 계산 영역입니다.

## 현재 구조

| 구성요소 | 위치 | 역할 |
|---|---|---|
| Graph | `src/route_engine/graph/` | DB 도보망을 NetworkX Graph로 준비·필터·직렬화 |
| Profile | `src/route_engine/profiles.py` | 사용자 선호 가중치와 차단 tags 정의 |
| Scoring | `src/route_engine/scoring/` | WalkEdge 속성과 Profile을 경로 비용으로 계산 |
| Engine | `src/route_engine/engines/` | 순환·편도 경로 탐색 알고리즘 |

## 계약 문서

- [경로 그래프 계약](graph_contract.md)

## Engine 반환 계약

- `circular_beam`(`CircularBeamEngine`)·`oneway_beam`(`OnewayBeamEngine`)·`oneway_astar`(`OnewayAstarEngine`)·`gps_art`(`GpsArtEngine`)·`waypoint`(`WaypointComposerEngine`) 5개 엔진의 `run()`은 모두 `List[WalkRouteResponse]`를 반환한다.
- 이 중 `circular_beam`·`oneway_beam`·`oneway_astar`의 `find_path()`는 노드ID 경로 후보를 `list[list[int]]`로 감싸서 반환한다. `gps_art`·`waypoint`는 자체 `find_path()`가 없다 — 대신 다른 엔진들의 `run()` 결과를 조합(`WaypointComposerEngine`)하거나 그 조합에 위임(`GpsArtEngine`)해서 최종 경로를 만든다.
- `circular_random`·`oneway_random`은 2026-08-07부터 최대 3개까지 벡터로 다양화한 후보를 반환한다(상세는 아래 "후보 다양화(벡터 score 기반)" 절 참고). `oneway_shortest`·GPS Art, 그리고 경유지 조합 중 다양화할 대안이 없는 경우(예: 모든 leg가 `oneway_shortest`)는 여전히 1개만 반환한다.
- `oneway_shortest` 모드의 실제 사용 엔진은 `dijkstra.py`(`OnewayDijkstraEngine`)에서 `oneway_astar.py`(`OnewayAstarEngine`)로 교체되었다. 배경·현재 사용처는 바로 아래 "oneway_shortest 엔진: Dijkstra → A*(ALT) 교체" 절 참고.
- `route_service.get_route()`도 같은 계약(`List[WalkRouteResponse]`)으로 반환한다. POI 조회는 성공한 후보 전부에 적용하고, `RouteHistory` 저장은 아직 대표 후보(리스트의 첫 번째)만 한다 — 사용자가 실제로 어떤 후보를 골랐는지 아직 API로 전달받지 않기 때문이며, 그 흐름이 생기면 선택된 후보를 저장하도록 바꿀 예정이다(`route_service.py`의 `TODO` 주석 참고). 리스트 전체는 그대로 반환한다.
- `OnewayAstarEngine._heuristic`은 그래프 로드 시 `precompute_landmarks(G)`(`oneway_astar.py`)가 미리 채워둔 노드 속성 `landmark_dist`를 그대로 참조한다. 이 함수는 2026-08-07 이전까지 `benchmarks/*.py`에서만 호출됐고 `dependencies.init_route_service()`(실제 서버·스크립트 부팅 경로)에는 연결돼 있지 않아서, 그래프가 정상 로드돼도 `oneway_shortest`·GPS Art(내부적으로 `WaypointComposerEngine`을 거쳐 `OnewayAstarEngine`을 씀) 둘 다 A* 탐색 단계에서 `KeyError: 'landmark_dist'`로 실패했다(그래프 미로딩으로 인한 `NO_NEAREST_START_NODE`에 가려져 있다가 그래프 데이터 복구 후 GPS Art 실행 검증 중 드러남). `dependencies.py`의 `init_route_service()`에 `precompute_landmarks(G)` 호출을 추가해 수정했다(2026-08-07).

## 후보 다양화(벡터 score 기반)

**왜 필요한가**

- beam search(`oneway_beam.py`/`circular_beam.py`)는 내부적으로 여러 후보(`_BEAM_WIDTH=8`)를 유지하다가도, 최종적으로는 안전·자연·평지 등을 전부 하나의 스칼라(`custom_score`)로 블렌딩한 기준 하나로만 후보를 좁혔다 — 그래서 여러 개를 뽑아도 사실상 비슷한 경로만 나오는 문제가 있었다.
- `target_km`(거리 허용오차) 자체는 이 다양화와 무관하게 여전히 1순위 조건이다 — 벡터 비교는 목표 거리를 만족(또는 가장 근접)하는 후보 풀 안에서만 적용한다.

**벡터 score — `scoring_engine.py`**

- `compute_score_vector(graph) -> {(u, v): {"safety": cost, "nature": cost, "slope": cost, "convenience": cost, "accessibility": cost}, ...}`를 추가했다. 기존 `calculate_custom_score`/`compute_custom_score_lookup`은 전혀 수정하지 않았다 — 그래서 A*(`oneway_astar.py`의 ALT `min_ratio`)·GRASP·ALNS·RCSP 등 이 스코어 함수를 공유하는 다른 엔진에는 영향이 없다.
- 각 차원 값은 `length * (1 - feature)`다. `feature`(0~1, 1이 가장 좋음)가 1이면 0, 0이면 그 edge의 `length` 전체가 비용이 된다 — `custom_score`처럼 경로를 따라 그대로 합산할 수 있고, 모든 차원이 이미 미터 단위라 추가 정규화 없이 비교 가능하다.
- profile 가중치를 받지 않는다 — 대표 후보(아래 "후보 1")는 기존처럼 요청받은 profile의 가중 스칼라로 뽑고, 이 벡터는 나머지 후보를 가중치와 무관하게 다양화하는 용도로만 쓴다.

**경로별 벡터 합산과 다양화 선택 — `path_utils.py`**

- `PathUtils.path_score_vector(path, vector_lookup)`: `metrics()`가 `custom_score`를 합산하는 것과 같은 패턴으로, 경로를 따라 벡터를 성분별로 합산한다.
- `PathUtils.vector_distance(a, b)`: 두 벡터 사이 유클리드 거리.
- `PathUtils.select_diverse_paths(candidates, k=3)`: **후보 1**(`candidates[0]`, 호출부가 기존 스칼라 키로 이미 정한 대표)을 고정하고, 나머지 중 이미 뽑힌 것들과의 최소거리가 가장 큰 것을 greedy farthest-point(k-center) 방식으로 최대 `k-1`개 더 뽑는다. 최댓값이 아니라 **최솟값의 최댓값**을 기준으로 삼는 이유는, "다른 후보와는 멀어도 기존에 뽑힌 것 중 하나와 거의 같은" 사실상의 중복을 배제하기 위해서다. 후보가 `k`개 미만이면 있는 만큼만 반환한다. `payload` 자리에는 노드 ID 리스트뿐 아니라 `WalkRouteResponse` 등 어떤 타입도 그대로 통과시킬 수 있다(`TypeVar` 기반 제네릭).

**`oneway_beam.py`/`circular_beam.py`: 최종 3개 선택**

- 도착(또는 복귀) 연결에 성공한 완성 후보 전체를 모아 기존 정렬 키(`oneway_beam`은 `(over, overlap, density)`, `circular_beam`은 `(over, density)`)로 정렬한다. `over`(거리 허용오차)와 `overlap`(우회도, `oneway_beam` 전용)은 벡터에 넣지 않는다 — 둘 다 "이 모드에서 유효한 후보인가"를 정하는 조건이라, 트레이드오프 대상인 품질 벡터와 성격이 다르기 때문이다.
- **후보 1** = 이 정렬 키 기준 최상위(오늘까지의 단일 결과와 완전히 동일). **후보 2·3** = 후보 1과 같은 거리 등급(`over`가 같은 값)을 만족하는 후보들 안에서만, `compute_score_vector`로 계산한 5차원 벡터를 `select_diverse_paths`로 다양화해서 뽑는다.
- `OnewayBeamEngine`에 `last_path_nodes_by_candidate: list[list[int]]`를 추가했다 — 반환하는 모든 후보의 노드열을 반환 순서대로 보관한다. 기존 `last_path_nodes`(단일 필드)는 후보 1의 단축값으로 그대로 남겨 하위 호환을 유지한다. `OnewayAstarEngine`에도 인터페이스를 맞추기 위해 `last_path_nodes_by_candidate = [last_path_nodes]`(항상 후보 1개뿐이라 트리비얼)를 추가했다.
- `CircularBeamEngine`은 `last_path_nodes` 계열 자체가 없다 — `WaypointLegMode`가 `oneway_shortest`/`oneway_random`만 허용해서(`route_schema.py`) 순환 모드는 구조적으로 waypoint leg가 될 수 없고, 따라서 cross-leg 겹침 방지 대상이 아니기 때문이다.

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

## oneway_shortest 엔진: Dijkstra → A*(ALT) 교체

**무엇이 바뀌었나**

- `route_service.py`의 `base_engines[WalkMode.ONEWAY_SHORTEST]`가 `dijkstra.py`(`OnewayDijkstraEngine`)에서 `oneway_astar.py`(`OnewayAstarEngine`)로 교체됐다(커밋 `6429ab1`, 2026-08-06). 같은 커밋에서 엔진들의 `run()` 반환 타입을 `List[WalkRouteResponse]`로 통일하는 리팩터도 함께 들어갔다.
- A* 자체는 그 전에 `benchmarks/`(`astar_solver.py`)용으로 먼저 작성됐고(커밋 `8a2eb10`, 2026-08-02), 초기 휴리스틱을 랜드마크 기반 ALT 방식으로 교체한 뒤(커밋 `f9c96b0`, 2026-08-03) `route_service.py`에 연결됐다.

**왜 A*(ALT)인가 — 휴리스틱 구조**

- `precompute_landmarks(G)`(`oneway_astar.py`)가 그래프 경계 근방 8개 지점을 랜드마크로 선정하고(`_select_landmarks`: 위도·경도 극값 + 대각 극값 4개), 각 랜드마크에서 전체 노드까지 `length`(profile 무관 실거리) 기준 Dijkstra 최단거리를 미리 계산해 노드 속성 `landmark_dist`(랜드마크별 거리 리스트)에 저장한다.
- `_heuristic(node, target)`은 두 노드의 `landmark_dist` 차이 중 최댓값(삼각부등식 하한, ALT의 핵심 아이디어)에 그래프 전체의 최소 cost/length 비율(`_min_ratio`)을 곱해 반환한다 — profile 가중치가 걸린 비용 함수에 대해서도 admissible(과대추정하지 않음)하도록 스케일을 맞추는 부분이다.
- Dijkstra(`dijkstra.py`)는 이런 휴리스틱 없이 `nx.shortest_path`(사실상 Dijkstra)로 균일하게 탐색한다 — 정보 없는 탐색이라 A*보다 더 많은 노드를 방문하는 경향이 있지만, 별도의 사전 계산(랜드마크·`landmark_dist`)이 필요 없다는 차이가 있다.

**`OnewayDijkstraEngine`의 현재 상태 — production에서는 죽은 코드**

- `route_service.py`·`waypoint.py`(`_LEG_ENGINES`)·`gps_art.py` 등 실제 요청을 처리하는 코드 경로 어디에서도 더 이상 `OnewayDijkstraEngine`을 참조하지 않는다.
- `benchmarks/solvers/dijkstra_solver.py`(A*와 나란히 비교하기 위한 baseline)·`benchmarks/benchmark.py`의 `SOLVER_REGISTRY`·`benchmarks/run_all_scenarios.py`의 `ONEWAY_ALGOS` 목록에서만 여전히 쓰인다.
- `tests/`에는 `OnewayDijkstraEngine`을 다루는 테스트가 하나도 없다 — 회귀 검증 없이 benchmark 용도로만 유지되는 상태다.
- **알려진 불일치**: `OnewayDijkstraEngine.run()`은 아직도 `WalkRouteResponse`를 리스트가 아닌 단일 값으로 반환한다 — 2026-08-06 리팩터 때 형제 엔진(`CircularBeamEngine`/`OnewayBeamEngine`/`OnewayAstarEngine`)은 전부 `List[WalkRouteResponse]`로 맞췄지만 `dijkstra.py`는 함께 수정되지 않았다. 지금은 어디서도 호출하지 않아 문제가 없지만, 나중에 이 엔진을 다시 연결하면 `results[0]` 언패킹 코드와 그대로 충돌한다.

**부팅 시 필수 의존성**

- A*를 쓰려면 그래프 로드 직후 `precompute_landmarks(G)`가 반드시 호출되어 `landmark_dist`가 채워져 있어야 한다(안 하면 `KeyError: 'landmark_dist'`) — 이 부팅 배선 버그와 수정 내역은 위 [Engine 반환 계약](#engine-반환-계약) 항목에서 다룬다.

**벤치마크 — 저장소에 커밋된 비교 수치는 없음**

- `benchmarks/runner/test_oneway_shortest_path.py`가 Dijkstra·양방향 Dijkstra·A*의 경로 비용 일치성과 지연시간을 비교하도록 만들어져 있다(`LATENCY_REPEAT`만큼 반복 측정 후 `benchmarks/results/oneway_shortest_path/bidir_astar_latency.csv`에 기록). 이 CSV는 로컬 실행 시에만 생성되며 저장소에는 커밋돼 있지 않다 — 즉 "A*가 실제로 더 빠르다/경로 품질이 같다"는 수치는 이 문서 작성 시점 기준 재현된 적이 없다.
- `benchmarks/run_all_scenarios.py`도 `dijkstra-oneway`를 시나리오 비교 대상에 포함하지만, `oneway_shortest`/`oneway_astar`/`dijkstra-oneway`는 모두 `target_km`을 무시하는 순수 최단경로 알고리즘이라 이 스크립트가 계산하는 거리 이탈(`distance_deviation_km`) 지표는 편도 우회(`oneway_random`) 계열 solver와 직접 비교할 수 없다(스크립트 자체 주석에 명시).
- **아직 확인 안 된 것**: 실제 그래프 규모에서 Dijkstra 대비 A*(ALT)의 속도·품질 개선폭. 위 benchmark 스크립트를 로컬에서 실행해 수치를 남기기 전까지는 "왜 이 교체가 유의미한가"를 정량적으로 뒷받침하는 근거가 없다.

## Waypoint(경유지) 조합 엔진

- `waypoint.py`(`WaypointComposerEngine`)는 출발지 → 경유지들 → 목적지를 구간(leg)별로 나눠, 각 leg에 지정된 모드의 기존 편도 엔진(`OnewayAstarEngine`/`OnewayBeamEngine`)을 순차 호출해 하나의 경로로 이어 붙인다. 새 탐색 알고리즘은 추가하지 않고 기존 엔진을 조합만 한다.
- 입력은 `WaypointRouteInput`(`src/schema/route_schema.py`)이며 `waypoints`(경유지 좌표 리스트), `leg_modes`(leg별 모드), `leg_target_km`(leg별 목표 거리, `oneway_random` leg만 필수)로 구성된다. `len(leg_modes) == len(waypoints) + 1`이어야 한다.
- `leg_modes`/`leg_target_km`은 `WalkMode`/`Coordinate`를 그대로 쓰지 않고 `route_schema.py` 안에 로컬로 정의한 `WaypointLegMode`(`Literal["oneway_shortest", "oneway_random"]`)와 `WaypointCoordinate`를 쓴다. `route_schema.py -> walk_schema.py -> route_engine.profiles -> route_schema.py(Weights)`로 이어지는 기존 순환 임포트 때문에 `walk_schema.py`의 타입을 직접 가져올 수 없어서다.
- `WaypointComposerEngine`은 그래프를 직접 mutate하지 않고 leg 엔진에 그대로 넘기기만 하므로 `G.copy()`를 하지 않는다(`self.G = G`). 실제 mutation(예: `OnewayBeamEngine`의 `custom_score` 계산)은 그걸 하는 leg 엔진이 자체적으로 격리한다. 인접 leg의 경계 좌표는 동일한 `(lat, lon)` 값을 그대로 재사용해 노드 스냅 불일치를 방지한다.
- leg가 실패하면(그리고 아직 `oneway_shortest`로 시도하지 않았다면) `OnewayAstarEngine`으로 그 leg만 재시도한다(다른 엔진들의 `base_shortest` 대체와 같은 패턴). 그 재시도까지 실패해야 해당 leg에서 중단한다.
- 결과 상태(`_stitch`)는 모든 leg 성공 시 `SUCCESS`, 일부만 성공 시 `PARTIAL_ROUTE`(성공한 구간까지만 좌표·거리 반환), 첫 leg부터(재시도 포함) 실패하면 그 leg의 실패 status를 그대로 사용한다. `mode`는 이 조합 전용으로 추가한 `WalkMode.WAYPOINT`를 쓴다.
- `route_service.py`와 연동됐다(2026-08-07): `RouteService.base_engines[WalkMode.WAYPOINT] = WaypointComposerEngine`, `_build_engine()`이 `waypoints`/`leg_modes`/`leg_target_km`를 받아 `WaypointRouteInput`을 구성한다. LLM이나 API 호출자가 일부 leg만 지정해도 나머지는 `oneway_shortest`로 자동 패딩해 `len(leg_modes) == len(waypoints)+1` 불변식을 채운다. 각 waypoint 좌표도 origin/destination과 동일하게 `find_nearest_node_with_expansion` 사전 검증을 거친다.
- `walk_router.py`(직접 REST API)에는 아직 연동하지 않았다 — GPS Art와 마찬가지로 챗봇 경유만 지원한다.
- 챗봇 연동: `mode_tools.py`에 `select_waypoint`(`origin`/`waypoints`/`destination`/`legs` → `WayPointPreference`)가 추가됐고, `route_tools.py`에 `waypoint_route` tool이, `route_executor.py`의 `MODE_TOOL_MAP`에 `WalkMode.WAYPOINT: "waypoint_route"`가 추가됐다. `RouteExecutor.run`은 `WayPointPreference.legs`(`{mode, target_km}` 객체 리스트)를 `leg_modes`/`leg_target_km` 두 리스트로 분리해 tool 인자를 구성한다. 경유지 장소 검색은 `place_tools.py`의 `target="waypoint"`+`waypoint_index`로 식별하고, `interviewer.py`가 인덱스별 후보(`state.waypoint_candidates`)를 관리한다.
- leg별 `profile`/`custom_weights` 지정은 여전히 지원하지 않는다 — `RouteExecutor`가 계산한 공통 `profile`/`custom_weights` 하나를 `WaypointComposerEngine` 생성자를 통해 모든 leg에 동일하게 적용한다(변경 없음).
- `extraction.yaml`에 `select_waypoint` 선택 규칙(경유지 표현 판단, 순환 코스 처리, `waypoints`/`legs` 필드 추출, 판단 예시 3개)이, `interview.yaml`에 경유지 장소 검색 가이드(`target="waypoint"`+`waypoint_index` 지정, 인덱스 오검색 방지, 복수 경유지 확인 질문)가 추가됐다(2026-08-07).
- **아직 확인 안 된 것**: 위 prompt 가이드가 추가됐다는 것과 실제 LLM이 대화에서 이 모드를 의도대로 선택·태깅한다는 것은 다른 문제다 — 정적 대조(YAML 파싱, `load_prompt(...).format(...)` 렌더링 확인)만 했고 실제 LLM 호출로 검증하지 않았다. 이 연동은 `tests/unit/test_routue_service.py::TestWaypointRouting`(mock 엔진 기반 4개 테스트) + 기존 `test_waypoint_engine.py`(엔진 자체 단위 테스트)로만 확인했고, 실제 그래프·LLM·Kakao를 사용한 실행 검증은 하지 않았다.

**leg 간 경로 겹침 방지(visited_nodes 페널티)**

- `OnewayAstarEngine`/`OnewayBeamEngine`은 이제 선택적 생성자 파라미터 `visited_nodes: Optional[set] = None`을 받는다. 기본값(미지정, 빈 set)이면 기존 동작과 완전히 동일하다 — `route_service.py`가 단독으로 쓰는 일반 편도 요청에는 영향이 없다.
- `WaypointComposerEngine.run()`은 leg마다 성공한 경로의 노드열을 `visited_nodes` 집합에 누적하고, 다음 leg의 엔진(재시도 포함)에 그 집합을 전달한다. 각 엔진은 `PathUtils.connect_to`의 `revisit_penalty`와 동일한 패턴(`_RETURN_REVISIT_PENALTY`, 5배)으로, 도착지 자신을 제외한 기방문 노드로 가는 엣지 가중치에 페널티를 곱해 우회를 유도한다.
- `OnewayAstarEngine`은 `find_path()`가 최적화하는 가중치 함수 자체에 페널티가 들어가므로, 페널티가 있으면 순수 최단경로가 아니라 "기방문 노드를 피하는 최단경로"를 반환한다 — leg 라벨이 `oneway_shortest`여도 마찬가지다.
- `OnewayBeamEngine`은 최종 경로 선택이 `target_km` 일치도를 최우선 기준(`_rank_key`의 첫 정렬 키)으로 삼기 때문에, 페널티가 최종 경로 선택에 항상 우선하지는 않는다 — 목표 거리에 더 가까운 경로가 있으면 페널티를 감수하고도 그 경로를 선택할 수 있다. 페널티는 후보 확장 단계(`_find_start_to_waypoint`의 cost 누적)와 도착 연결 단계(`_find_waypoint_to_end` → `connect_to`)에는 항상 반영되지만, 최종 승자가 반드시 우회로가 되는 것은 보장하지 않는다.
- 각 엔진에는 `last_path_nodes` 속성이 추가됐다 — 가장 최근 `run()`이 실제로 사용한 노드열(`OnewayBeamEngine`은 왕복 가지 제거 후)이며, `WaypointComposerEngine`이 다음 leg의 `visited_nodes`를 누적할 때 이 값을 읽는다.
- `GpsArtEngine`은 내부적으로 `WaypointComposerEngine`을 그대로 쓰므로 별도 수정 없이 이 겹침 방지 로직을 그대로 물려받는다 — 도형이 스스로 교차하는 경우 겹치는 구간을 우회하려고 시도한다(단, 위 `OnewayBeamEngine`의 한계와 동일하게 항상 보장되지는 않는다).

## GPS Art

경유지 반영 경로를 응용해, 도형 모양대로 걷는 경로를 생성한다. route_engine 계산(`GpsArtEngine`)과 이미지 생성·윤곽선 추출(`GpsArtService`, `src/service/route/gps_art_service.py`) 두 layer로 나뉜다.

**`GpsArtEngine`(`gps_art.py`, route_engine 계산)**

- 입력은 `GpsArtRouteInput`(`src/schema/route_schema.py`): `shape_points`(정규화된 도형 좌표, 로컬 단위·단위 없음), `origin_lat`/`origin_lon`(배치할 중심 위경도), `target_km`(목표 총 이동 거리). `shape_points`는 검증 시점에 첫 점=마지막 점이 되도록 자동으로 닫힌다.
- `_map_to_geo`: `shape_points`를 실제 위경도로 변환한다. 도형의 로컬 단위 둘레와 `target_km`(도로망 계수 1.4로 나눠 직선 기준으로 역산)의 비율로 scale을 구하므로, 입력 좌표가 어떤 절대 크기·단위든 상관없이 항상 `target_km`에 맞게 배치된다(스케일 불변).
- `_snap_to_nodes`: 변환된 위경도를 그래프 최근접 노드로 스냅한다. 연속으로 같은 노드에 스냅되면(도로망이 성긴 구간) 하나로 합친다.
- 스냅된 노드열을 `WaypointRouteInput`으로 변환해 `WaypointComposerEngine`에 위임한다. 도형 왜곡을 막기 위해 모든 leg를 `oneway_shortest`로 고정하고, `custom_weights`로 모든 가중치를 0으로 채운 `_DISTANCE_ONLY_WEIGHTS`를 명시적으로 넘긴다(2026-08-07 수정). `WaypointComposerEngine(waypoint_inp, self.G)`처럼 `custom_weights`를 아예 안 넘기면 `get_profile(None)`이 DEFAULT 프로필(safety=0.5·nature=0.5·slope=0.5·convenience=0.2, 전혀 중립이 아님)로 떨어져서, `scoring_engine.py`의 `bonus`(분모)가 안전·자연·편의 점수 좋은 엣지를 실제보다 "더 짧게" 취급해 도형이 그쪽으로 휘어지는 문제가 있었다 — GPS Art 실행 검증 중 실제로 관측됨. 모든 가중치를 0으로 두면 `custom_score`가 사실상 `length × comfort_penalty`(터널·지하철망 등 최소 페널티만 남음)가 되어 실제 거리에 훨씬 가까운 경로를 따른다.
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
- 입력 Graph와 Profile을 받아 경로 계산 결과를 반환합니다.

## V1 점수 방향

- 안전·자연·공원·랜드마크·러닝·편의·접근성 값은 확인된 Edge에만 제한 가점한다.
- 데이터가 없는 지역의 `0`은 감점이 아니라 중립이다.
- `slope_score`는 평탄도이며 `1.0`에 가까울수록 평지다.
- `is_vehicle_caution`은 `child` 가중치에 따른 회피 페널티다. `child_score` 자체는 안전 가점으로 사용하지 않는다.
- 터널·육교·지하철망·건물 내부는 완전 차단하지 않고 보수적인 쾌적도 페널티를 적용한다.
- `blocked_tags`에 명시된 검증된 WalkEdge Tag만 탐색 비용을 무한대로 만들어 제외한다.
- 기본 프로필은 실재하지 않는 `underground` Tag를 자동 차단하지 않는다.

프로필에는 기존 유형 외에 `convenient`, `accessible`이 있다.
내부 `accessible`은 사용자에게 `이동이 편한 길`로 표시한다. 리프트·엘리베이터
인접 Edge와 평탄한 길을 제한적으로 선호할 뿐, 완전한 무장애 경로를 보장하지 않는다.
