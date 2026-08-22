# 최단 경로 엔진 가중치 → 거리 전용 전환 제안

> 상태: Archive (구현 완료 — §7 참고)
> 기준일: 2026-08-23
> 기준 문서: [route_engine/README.md](../route_engine/README.md), [route_engine/graph_contract.md](../route_engine/graph_contract.md)
> 대상 코드: `src/route_engine/engines/dijkstra.py`, `oneway_astar.py`, `oneway_bi_astar.py`, `src/route_engine/scoring/scoring_engine.py`

## 1. 목적과 범위

최단 경로류 엔진(Dijkstra, A*, 양방향 A*)의 탐색 가중치를 현재의 안전·자연·평지 등 블렌딩된 `custom_score` 대신 **거리(length)만**으로 쓰도록 바꾸는 설계를 조사·제안한다. 이 문서는 조사와 설계 결정 항목까지만 다루며, 코드를 변경하지 않는다.

**범위**: `OnewayDijkstraEngine`, `OnewayAstarEngine`, `OnewayBidirectionalAstarEngine`의 weight 계산 경로.

**제외**: `beam`/`grasp`/`alns`/`rcsp`/`plateau`, `circular_*` 계열 — 이들은 `calculate_custom_score`(그래프 mutation) 기반이라 이번 범위 밖. 실제 구현은 승인 후 별도 작업.

## 2. 현재 방식 요약

| 엔진 | 파일 | 탐색 방식 | weight 출처 |
|---|---|---|---|
| `OnewayDijkstraEngine` | `dijkstra.py` | 단방향(`nx.shortest_path`) | `compute_custom_score_lookup`의 `custom_score` |
| `OnewayAstarEngine` | `oneway_astar.py` | 단방향(`nx.astar_path`, ALT 휴리스틱) | 동일 |
| `OnewayBidirectionalAstarEngine` | `oneway_bi_astar.py` | 양방향(`OnewayAstarEngine` 상속, `find_path()`만 교체) | `OnewayAstarEngine`과 동일한 `_weight_fn` 그대로 상속 |

**사실 확인(작성 시점, 2026-08-23 오전)**: 이 시점 기준 저장소에 양방향 Dijkstra "엔진 클래스"는 없었다. 다만 `benchmarks/runner/test_oneway_shortest_path.py`가 `nx.bidirectional_dijkstra`(NetworkX 내장 함수)를 직접 호출해 속도 비교에만 쓰고 있었다 — production 엔진 클래스로 감싼 형태는 아니었다. "양방향/단방향" 조합이 엔진 클래스로 실제 존재하는 건 A* 쪽뿐이었고, Dijkstra는 단방향만 있었다. **이후 같은 날 §7에서 `OnewayBidirectionalDijkstraEngine`을 신설해 이 공백을 채웠다.**

**`custom_score` 계산식** (`scoring_engine.py:_compute_scores_array`):

```
custom_score = length * slope_penalty * caution_penalty * comfort_penalty / bonus
```

- `bonus`: safety·nature·landmark·convenience·accessibility 가중 곱 (전부 0이면 1)
- `slope_penalty`: `1 + (1-slope)*slope_w` (slope_w=0이면 1)
- `caution_penalty`: 어린이보호구역 인접 시 `child_w` 반영 (child_w=0이면 1)
- `comfort_penalty`: 터널(1.20)·육교(1.12)·지하철망(1.08)·건물내부(1.08) — **weight와 무관하게 항상 적용**
- `blocked_tags`에 해당하면 `inf`로 완전 차단 — **weight와 무관하게 항상 적용**

**기존 유사 사례**: `gps_art.py`의 `_DISTANCE_ONLY_WEIGHTS`(모든 `Weights` 필드 0)가 이미 "가중치 거리 전용화"를 한 번 해봤다. 다만 이건 **완전한 거리 전용이 아니다** — `comfort_penalty`와 `blocked_tags`는 weight 0과 무관하게 그대로 남는다(주석 `gps_art.py:28-30`에 명시).

## 3. 변경안 — 설계 결정 필요 항목

| 항목 | 옵션 | 트레이드오프 |
|---|---|---|
| 구현 방식 | (A) `custom_weights`를 전부 0으로 고정 (`_DISTANCE_ONLY_WEIGHTS` 재사용) | 코드 변경 최소. 단, `comfort_penalty`(터널 등 최대 +20%)와 `blocked_tags` 차단은 그대로 남아 "순수 거리"가 아님 |
| | (B) weight 함수를 `scoring_engine`을 거치지 않고 그래프의 `length` 속성 직접 사용 (`weight="length"`, `precompute_landmarks`가 이미 쓰는 패턴과 동일) | 진짜 거리만 반영. 단, `blocked_tags`(위험 태그 차단)까지 사라져서 원래 걸러지던 엣지도 통과 가능해짐 |
| | **(C) weight=length + blocked_tags만 유지** — **Dijkstra에 채택(2026-08-23)** | `bonus`(safety/nature 등)·`slope_penalty`·`caution_penalty`·`comfort_penalty`는 전부 무시하고 거리만 반영하되, 위험 태그 차단(`blocked_tags` → `inf`)만은 그대로 유지. (A)와 (B) 사이의 절충안 |
| 적용 대상 | (A) Dijkstra만 — 1차로 검토 | 현재 production 미사용(dead code, `route_engine/README.md` 확인됨)이라 실질 영향 없이 먼저 검증 가능 |
| | (B) Dijkstra + A* + 양방향 A* 전부 — **최종 채택(2026-08-23)** | `oneway_shortest` 모드(production 사용 중인 A*)의 실제 응답이 바뀜. Dijkstra 적용 직후 같은 날 A*·양방향 A*까지 확장 |
| 휴리스틱(A*만 해당) | (기존) 랜드마크 기반 ALT | `precompute_landmarks(G)` 부팅 의존성 필요, `min_ratio` 보정 필요 |
| | **Haversine 직선거리 — 채택(2026-08-23)** | weight가 이제 거리(length) 그대로이므로 직선거리 ≤ 실제 거리(삼각부등식)가 항상 성립 — 보정 불필요, admissible. `PathUtils._haversine_m` 재사용. 대신 ALT보다 하한이 느슨해 탐색 노드 수는 늘어날 수 있음(측정 안 함) |

### 3.1 구현 방식(구현 완료)

- `scoring_engine.py`에 `compute_distance_only_lookup(graph, blocked_tags)` 추가 — 기존 `_get_feature_cache`(캐시 재사용)에서 `length`와 `tags_list`만 읽어 `blocked_tags` 매칭 시 `inf`, 아니면 `length`를 반환. `bonus`/`slope_penalty`/`caution_penalty`/`comfort_penalty`는 전혀 계산하지 않는다.
- `dijkstra.py`·`oneway_astar.py`의 `run()`에서 `compute_custom_score_lookup(...)` 호출을 `compute_distance_only_lookup(self.G, self.blocked_tags)`로 교체.
- `self.blocked_tags`(`profile_config.blocked_tags`)는 기존과 동일하게 유지되므로 프로필별 차단 태그는 그대로 반영된다.
- `oneway_astar.py`의 `_heuristic`을 랜드마크 ALT에서 `self.utils._haversine_m(...)`(Haversine 직선거리)로 교체. weight=length이므로 `min_ratio` 보정이 필요 없어져 관련 필드(`self._min_ratio`)를 제거했다.
- `OnewayBidirectionalAstarEngine`(`oneway_bi_astar.py`)은 `run()`을 오버라이드하지 않아 위 변경이 상속으로 자동 적용됨 — 별도 수정 불필요함을 확인했다.
- **부수 영향**: `path_cost()`(`dijkstra.py`, `oneway_astar.py`)의 반환 의미가 "누적 `custom_score`"에서 "누적 거리(경로에 blocked edge가 있으면 `inf`)"로 바뀜 — docstring 갱신 완료. `self.weights`는 더 이상 weight 계산에 쓰이지 않지만 `run()`의 로그 출력에는 남아 있다.
- **죽은 코드 제거**: `precompute_landmarks()`·`_select_landmarks()`(`oneway_astar.py`), `landmark_dist` 노드 속성 참조를 전부 제거했다. 연쇄적으로 `dependencies.py`(`init_route_service()` 부팅 호출), `benchmarks/benchmark.py`, `benchmarks/run_all_scenarios.py`의 import·호출도 함께 제거했다(안 지우면 `ImportError`).

## 4. 영향 범위

| 파일 | 실제 변경 | 상태 |
|---|---|---|
| `src/route_engine/scoring/scoring_engine.py` | `compute_distance_only_lookup(graph, blocked_tags)` 추가 | 완료 |
| `src/route_engine/engines/dijkstra.py` | weight 계산을 `compute_distance_only_lookup`로 교체, `path_cost()` docstring 갱신 | 완료 |
| `src/route_engine/engines/oneway_astar.py` | weight 계산 교체, `_heuristic`을 Haversine으로 교체, `precompute_landmarks`/`_select_landmarks`/`_min_ratio` 제거 | 완료 |
| `src/route_engine/engines/oneway_bi_astar.py` | `OnewayAstarEngine` 상속 구조라 자동 반영 확인, 코드 변경 없음 | 완료(변경 불필요 확인) |
| `src/interfaces/dependencies.py` | `precompute_landmarks(G)` 부팅 호출·import·관련 주석 제거 | 완료 |
| `benchmarks/benchmark.py`, `benchmarks/run_all_scenarios.py` | `precompute_landmarks` import·호출 제거(그대로 두면 `ImportError`) | 완료 |
| `benchmarks/solvers/dijkstra_solver.py`, `astar_solver.py`, `bi_astar_solver.py` | 세 solver 모두 `engine.run()`을 안 거치고 weight 계산을 자체 복제하던 부분을 `compute_distance_only_lookup(engine.G, engine.blocked_tags)`로 교체. `astar_solver.py`/`bi_astar_solver.py`의 `engine._min_ratio = ...` 대입도 제거(더 이상 존재하지 않는 필드) | 완료 |

## 5. 조사 완료 기준

- 현재 3개 엔진의 weight 출처와 계산식이 코드 대조로 확인됨
- `_DISTANCE_ONLY_WEIGHTS` 선례가 "완전한 거리 전용이 아님"까지 확인됨
- 양방향 Dijkstra가 존재하지 않는다는 사실이 코드 대조로 확인됨

## 6. 승인과 구현 완료 기준

- 팀이 §3의 두 항목(구현 방식, 적용 대상)을 승인한다.
- 승인된 설계로 §4 대상 파일 변경을 별도 구현 작업 단위로 진행한다.
- 구현 완료 후 `route_engine/README.md`의 "oneway_shortest 엔진" 절 등 관련 Current 문서를 코드에 맞게 갱신한다.
- 이 Proposal 자체는 코드를 변경하지 않으며, 구현은 승인 후 별도 커밋에서 진행한다.

## 7. 구현 결과(2026-08-23)

§3의 설계 결정은 다음으로 확정·구현되었다.

- **구현 방식**: 옵션 (C) — `weight=length` + `blocked_tags`만 유지. `bonus`/`slope_penalty`/`caution_penalty`/`comfort_penalty`는 전부 무시.
- **적용 대상**: Dijkstra로 먼저 검증한 뒤, 같은 날 A*·양방향 A*까지 전부 확장(옵션 B).
- **A* 휴리스틱**: 랜드마크 ALT → Haversine 직선거리로 교체(§3 표에 추가된 결정 항목, 최초 proposal 작성 시점엔 없었음).
- 상세 변경 내용은 §3.1·§4 표 참고. `route_engine/README.md`의 "oneway_shortest 엔진: 거리 전용(distance-only) weight + Haversine 휴리스틱" 절도 함께 갱신했다.

## 8. 추가 확장 — 양방향 Dijkstra 엔진 신설(2026-08-23, 원 제안 범위 밖)

§2에서 확인했듯 저장소에 양방향 Dijkstra "엔진 클래스"가 없었는데, 팀원이 벤치마크 러너(`nx.bidirectional_dijkstra` 직접 호출)로 이미 테스트해봤다는 사실이 확인되면서 같은 패턴을 production 엔진으로도 만들어달라는 요청을 받아 추가했다.

- `src/route_engine/engines/oneway_bi_dijkstra.py`에 `OnewayBidirectionalDijkstraEngine` 신설. `OnewayBidirectionalAstarEngine`(`oneway_bi_astar.py`)이 `OnewayAstarEngine`을 상속해 `find_path()`만 양방향으로 바꾸는 것과 동일한 패턴으로, `OnewayDijkstraEngine`을 상속해 `find_path()`만 `nx.bidirectional_dijkstra`로 교체했다.
- `run()`은 그대로 상속되므로 `compute_distance_only_lookup(self.G, self.blocked_tags)`가 자동 적용된다 — 거리(length)만 weight로 쓰고 `blocked_tags`는 차단하는 조건을 그대로 만족한다.
- `benchmarks/solvers/bi_dijkstra_solver.py` 신설(`dijkstra_solver.py`와 동일 구조), `benchmarks/benchmark.py`의 `SOLVER_REGISTRY`와 `benchmarks/run_all_scenarios.py`의 `ONEWAY_ALGOS`에 `"bi-dijkstra-oneway"`로 등록했다.
- `OnewayDijkstraEngine`과 마찬가지로 `route_service.py`/`__init__.py`에는 연결하지 않았다 — production에서는 여전히 죽은 코드(벤치마크 전용)로 유지되는 상태다.

## 9. 회귀 발견과 수정 — Haversine 휴리스틱의 admissibility 전제(2026-08-23)

`tests/` 전체 회귀 테스트를 돌려본 결과, 이번 변경으로 실제 버그가 2건 발견되어 함께 수정했다.

- **`ImportError`**: `tests/unit/test_visited_nodes_penalty.py`, `test_gps_art_engine.py`, `test_waypoint_engine.py` 세 파일이 삭제된 `precompute_landmarks`를 여전히 import·호출하고 있었다. `src/`·`benchmarks/`만 확인하고 `tests/`를 빠뜨린 게 원인 — import와 fixture 호출을 제거해 수정했다.
- **경로 선택 오류(더 심각함)**: `test_visited_nodes_penalty.py`의 `diamond_graph` fixture는 좌표(lat/lon)와 edge `length`를 서로 무관하게 임의로 정해뒀다(예: 실제 좌표상 직선거리 345m인 두 노드 사이 edge를 100m로 선언). 예전 ALT 휴리스틱은 `length` 기반 Dijkstra로 `landmark_dist`를 직접 계산해서 좌표와 무관하게 항상 admissible했지만, 새 Haversine 휴리스틱은 **좌표 자체가 실제 도로 length보다 짧은 직선거리를 보장해야 admissible**하다. 이 fixture는 그 전제를 어겨서 `OnewayAstarEngine`이 실제로 **더 긴 경로를 반환하는 회귀**가 테스트 실패로 드러났다.
  - 수정: fixture 좌표를 모든 declared length보다 훨씬 작은 범위(노드 간 수 미터 이내)로 좁혀 admissible을 항상 만족하도록 재조정. 관련 하드코딩된 좌표 단언문(`WaypointComposerEngine` 테스트 등)도 새 좌표로 갱신.
- **검증되지 않은 가정**: 실제 production 그래프(OSM/Kakao 도로망)는 도로 `length_m`이 물리적으로 두 끝점 간 직선거리보다 짧을 수 없으므로 이 문제가 재현되지 않을 것으로 예상하지만, 실측으로 확인하지는 않았다.
- 이 회귀 수정 이후 `tests/unit/`의 route_engine 관련 전체(위 3개 파일 + `test_scoring_engine.py`·`test_scoring_engine_regression.py`·graph 관련 4개 파일)를 재실행해 전부 통과함을 확인했다(`.venv/Scripts/python.exe -m pytest ...`). `test_auth_service.py`·`test_banner_service.py`·`tests/integration/test_api.py`·`test_path_utils.py`의 일부 실패는 이번 변경과 무관한 기존 상태로 확인됨(수정 대상 아님).

**남은 항목**: 없음. 아래 항목까지 전부 정리됐다.
- `benchmarks/solvers/{dijkstra,astar,bi_astar}_solver.py`: `compute_distance_only_lookup`로 교체 완료(2026-08-23).
- `benchmarks/runner/test_oneway_shortest_path.py`(2026-08-23): `scoring_engine.py`나 실제 엔진 클래스를 참조하지 않고 자체 재구현한 별도 스크립트였지만, production과 동일한 기준(weight=length(m), heuristic=Haversine 직선거리(m))으로 맞춰 갱신했다. `PROFILE_WEIGHTS`/`compute_custom_score`/`compute_min_ratio`는 profile 블렌딩 자체가 없어져 삭제했고(현재 모든 profile의 `blocked_tags`가 비어 있어 profile 간 weight 차이가 아예 없어졌기 때문), `haversine_km` → `haversine_m`으로 바꿔 `length`(m)와 단위를 맞췄다(기존 버전은 km 단위 직선거리에 m 단위 length 기반 비율을 곱해 사실상 사용되지 않는 미검증 스크립트에서 단위가 어긋나 있었다). `weight_fn`/`heuristic` 계산도 이제 profile과 무관해 시나리오 루프 밖에서 한 번만 수행한다.
