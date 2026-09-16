# turn_cost 경로 형상 분포 — 탐색적 1차 관측

> **주의**: 이 폴더의 결과는 **확정된 결론이 아니라 탐색적(exploratory) 1차 관측**입니다.
> 반복 측정 없이 각 엔진 1회 실행만 수행했고, 일부 엔진은 공식 어댑터를 우회해서
> 얻은 값입니다. 엔진 우열이나 보행 편안함의 확정 근거로 인용하지 마세요.
> (후속 반복 실행·어댑터 수정 이후 이 폴더 내용은 갱신될 수 있습니다.)

## 실행 정보

| 항목 | 내용 |
|---|---|
| 실행일 | 2026-09-16 |
| 그래프 | `benchmarks/fixtures/route_nodes.parquet` + `route_edges.parquet` (서울 도보 그래프 fixture) |
| 노드 수 / 엣지 수 | 160,328 / 223,927 |
| 시나리오 | `benchmarks/datasets/route_engine.json`의 순환(circular) 시나리오 25개 |
| 분석 스크립트 | [turn_cost_distribution_check.py](turn_cost_distribution_check.py) |
| 원본 결과 | [turn_cost_distribution.csv](turn_cost_distribution.csv) |
| 성공 실행 | 총 123회 |

## 대상 엔진과 성공률

| 엔진 | 시도 | 성공 | 비고 |
|---|---|---|---|
| beam-circular | 25 | 25 | **공식 어댑터 우회** — 아래 "알려진 이슈" 참고 |
| grasp-circular | 25 | 25 | |
| alns-circular | 25 | 23 (92%) | 2건은 "유효 순환 경로 없음"으로 정상 실패(turn_cost와 무관) |
| rcsp-circular | 25 | 25 | |
| grasp-wp-local | 25 | 25 | |

## 이번 배치에서 제외한 엔진

25개 시나리오 전수 실행 비용이 현실적으로 높아 제외했다(1회 소요시간, 사전 측정):

| 엔진 | 1회 소요시간 |
|---|---|
| grasp-wp-vnd | 약 54초 |
| grasp-wp-alns | 약 47초 |
| grasp-wp-vns | 약 591초(약 10분) |

**이 결과는 위 세 엔진의 회전량 특성을 포함하지 않는다.** (대표 시나리오 소수 실행은 `slow_engines_sample/`에 별도 진행 예정/진행 중.)

## 지표 정의

- `total_turn_deg`: 경로 전체의 누적 방향 변화(회전각의 절대값 합, 도)
- `turn_deg_per_km`: `total_turn_deg`를 실제 이동 거리(km)로 정규화한 값
- `max_turn_deg`: 경로 내 가장 큰 단일 회전각
- `turn_count_ge_45/60/90`: 해당 각도 이상인 회전의 개수(잠정 운영 임계값 — 보편적 보행 불편 기준 아님)
- `undefined_turn_count`: 좌표 누락·0길이 벡터 등으로 정의할 수 없었던 회전 지점 수

## 요약 — 엔진별 회전량 통계 (1회 실행 기준)

| 엔진 | 시도 | 평균 총회전량(°) | p50(°) | p90(°) | 평균 최대회전각(°) | 평균 거리당회전량(°/km) |
|---|---|---|---|---|---|---|
| grasp-wp-local | 25 | 2,663.0 | 2,676.5 | 3,641.4 | 150.0 | 739.6 |
| beam-circular | 25 | 2,818.8 | 2,885.8 | 4,041.6 | 136.4 | 774.2 |
| alns-circular | 23 | 2,206.4 | 2,168.3 | 3,062.2 | 138.1 | 840.5 |
| grasp-circular | 25 | 3,731.1 | 3,538.2 | 5,684.7 | 156.7 | 1,038.6 |
| rcsp-circular | 25 | 4,580.9 | 4,750.0 | 6,287.1 | 131.9 | 1,288.0 |

**전체 candidate_turn_count 10,236건 중 undefined 0건(0.000%)** — 이 데이터셋에서는 좌표 누락·0길이 벡터 등 정의 불가 케이스가 발생하지 않았다. 다만 이는 "이번 데이터셋에 없었다"는 것이지, 방어 로직(`undefined_turn_reasons` 집계)을 제거해도 된다는 뜻이 아니다 — 단위 테스트와 방어 로직은 유지한다.

## 지표 간 순위 불일치 (중요 — 단일 지표로 대체하지 말 것)

`total_turn_deg`/`turn_deg_per_km`(누적 방향 변화)과 `max_turn_deg`/`turn_count_ge_90`(급회전 패턴)은 **서로 다른 현상을 측정**하며, 실제로 순위가 갈린다.

```
turn_deg_per_km 순위(낮을수록 완만):
  grasp-wp-local < beam-circular < alns-circular < grasp-circular < rcsp-circular

turn_count_ge_90 순위(적을수록 급회전 적음):
  alns-circular < grasp-wp-local < beam-circular < grasp-circular < rcsp-circular
  ── alns-circular와 grasp-wp-local의 순서가 뒤집힌다.

max_turn_deg 순위(낮을수록 좋음):
  rcsp-circular < beam-circular < alns-circular < grasp-wp-local < grasp-circular
  ── rcsp-circular는 누적 지표 기준 최하위인데 "가장 큰 단일 회전"은 전체 중 가장 작다.
     (자잘한 회전이 많이 누적된 경로라는 뜻 — 총량만 보면 놓치는 정보)
```

**결론**: 누적 회전량 지표와 급회전 지표는 함께 보고해야 하며, 하나로 대체할 수 없다.

## 알려진 이슈 (이번 turn_cost 작업과 무관 — 별도 GitHub 이슈로 등록)

`benchmarks/solvers/_circular_engine_common.py::run_circular_engine`이 `CircularBeamEngine.find_path()`의 반환 타입(`list[list[int]]`, 대표 후보 3개)을 그대로 `prune_dead_ends()`(단일 경로 `list[int]` 기대)에 넘겨서, 공식 벤치마크 스위트로 `beam-circular`를 실행하면 항상 `TypeError: unhashable type: 'list'`로 실패한다. 이번 분석에서는 이 어댑터를 우회해 `engine.find_path()[0]`(대표 후보)을 직접 사용했으므로, **위 표의 `beam-circular` 결과는 공식 벤치마크 경로로 재현된 값이 아니다.** 어댑터 수정 후 재산출이 필요하다.

## 한계

1. **1회 실행 결과다.** GRASP/ALNS 계열은 확률적 요소가 있어 실행마다 경로·회전량이 달라질 수 있다.
2. **alns-circular 통계는 조건부(23/25 성공)다.** 실패 시나리오를 0으로 채우지 않았다.
3. **beam-circular는 어댑터 우회 결과다.**
4. **grasp-wp-vnd/vns/alns 특성은 포함하지 않는다.**
5. **45°/60°/90° 임계값은 보편적 보행 불편 기준이 아니라 잠정 운영 임계값이다.**

## 반복 실행 분산 확인 (`variance_sample/`)

대표 시나리오 5개(짧음~김 고르게, 기존 alns 실패 재현 시나리오 포함) × `grasp-wp-local`/`grasp-circular`/`alns-circular` × 5회 반복. 결과: [variance_results.csv](variance_sample/variance_results.csv), 스크립트: [variance_check.py](variance_sample/variance_check.py).

- **모든 (시나리오, 엔진) 조합에서 5회 반복 표준편차가 0.0이었다** — 같은 프로세스 안에서 반복 호출 시 완전히 동일한 경로가 나왔다. `beam-circular`/`rcsp-circular`도 별도 2회 비교에서 경로가 완전히 일치했다.
  - **주의**: 이건 "같은 Python 프로세스 안에서 반복 호출"한 결과다. 실제 벤치마크 스위트는 매 실행마다 새 프로세스를 띄우는(`multiprocessing`) 방식이라 시드 초기화가 다를 수 있고, 그 경우 결과가 달라질 가능성은 남아 있다 — "완전히 결정적"이 아니라 "이 실행 방식에서는 재현성이 확인됨"으로 표현한다.
  - `circular_09/alns-circular`는 5회 모두 동일하게 실패(우연이 아니라 일관된 실패).
  - 엔진별 `cv_total_pct`(alns 47.8%, grasp 59.2%, grasp-wp-local 32.9%)는 반복 간 분산이 아니라 **시나리오(거리·프로필) 차이에서 오는 자연스러운 변동**이다.

## 느린 엔진(grasp-wp-vnd/alns/vns) 대표 시나리오 확인 (`slow_engines_sample/`)

target_km 짧음/중간/김을 대표하는 시나리오 5개(vnd, grasp-wp-alns) 또는 2개(vns, 1회 10분이라 최소화)만 실행. 결과: [slow_engines_results.csv](slow_engines_sample/slow_engines_results.csv), 스크립트: [slow_engines_check.py](slow_engines_sample/slow_engines_check.py).

| 엔진 | 시도 | 평균 실행시간(초) | 평균 거리당회전량(°/km) | 평균 최대회전각(°) | 평균 90°↑ 횟수 |
|---|---|---|---|---|---|
| grasp-wp-alns | 5 | 25.1 | 756.9 | 156.7 | 6.8 |
| grasp-wp-vnd | 5 | 27.9 | 835.6 | 169.8 | 10.4 |
| grasp-wp-vns | 2 | 149.0 | 744.6 | 111.1 | 7.5 |

**같은 5개 시나리오만으로 8개 엔진을 공정 비교(거리당 회전량, 오름차순)**:

```
alns-circular(682.2) < grasp-wp-vns(744.6, n=2) < grasp-wp-alns(756.9) < beam-circular(810.2)
  < grasp-wp-local(835.6) ≈ grasp-wp-vnd(835.6, 아래 참고) < grasp-circular(850.1) < rcsp-circular(1267.1)
```

이 5개 시나리오만 보면 전체 25개 평균과 순위가 다르다(예: alns-circular가 이 5개에서는 최상위) — **표본이 다르면 순위가 바뀐다는 것 자체가 "25개 전체 대비 일반화하면 안 된다"는 근거**다.

### 조사 완료: `grasp-wp-vnd` == `grasp-wp-local` 현상의 원인 (2026-09-16 추가 조사)

5개 시나리오 전부에서 `grasp-wp-vnd`의 최종 결과가 `grasp-wp-local`과 노드ID까지 완전히 일치해, 실제 `vnd()`/`_local_search()` 메서드를 GRASP 반복(`grasp_iters=24`) 단위로 직접 호출해 비교했다(`circular_20` 기준, 재현 스크립트는 이 조사 전용으로 별도 저장하지 않고 1회성으로 실행함 — 필요시 아래 커맨드로 재현 가능).

**결론: 버그가 아니다.** 다음이 모두 코드로 직접 확인됐다.

- **VND는 실제로 실행되고 실제로 개선한다**: 24회 반복 중 9회에서 VND가 Local과 다른(그리고 목적함수 기준 명백히 더 나은) 경로를 만들었다. 예: 반복 0에서 Local은 `distance_error=84.4m, repeated_edge_ratio=0.122`, VND는 `distance_error=60.8m, repeated_edge_ratio=0.045`.
- **다만 "최종 채택 반복"이 우연히 겹쳤다**: GRASP은 24회 중 하나만 최종 채택하는데, 채택 기준(`RouteObjective.sort_key()`)이 `repeated_edge_ratio`(자기중첩)를 `distance_error_m`(거리 오차)보다 **우선** 순위로 둔다. 이 시나리오에서는 반복 1번(`repeated_edge_ratio=0.033`)이 최종 승자였는데, 하필 반복 1번은 VND가 추가 개선을 못 찾은(=Local과 이미 같은) 9회 중 하나가 아니었다. VND가 다른 22개 반복에서는 분명히 더 나은 경로를 찾았지만, 그중 어느 것도 반복 1번의 낮은 `repeated_edge_ratio`를 이기지 못해 최종 결과만 우연히 같아진 것이다.
- **호출 경로·어댑터 버그 없음**: `SOLVER_REGISTRY`가 서로 다른 클래스(`CircularGraspWaypointLocalEngine`/`CircularGraspWaypointVndEngine`)를 정확히 가리키며, 결과를 덮어쓰는 코드도 없다.

**일반화 주의**: 이건 `seed=42`·`rcl_size=8`·`grasp_iters=24`라는 특정 설정과 "자기중첩 최소화를 거리 정확도보다 우선"하는 목적함수 설계가 겹쳐 생긴, **이번 5개 샘플에 한정된 관측**이다. 다른 시나리오·시드에서는 VND가 Local을 실제로 앞지르는 결과가 나올 수 있다 — "VND와 Local이 항상 같다"고 일반화하면 안 된다.

## 다음 단계

- [완료] grasp-wp-local/grasp-circular/alns-circular 대표 샘플 반복 실행(분산 확인)
- [완료] grasp-wp-vnd/alns/vns 대표 시나리오 소수 실행
- [완료] grasp-wp-vnd == grasp-wp-local 경로 동일 현상 원인 조사 — 버그 아님, 최종 채택 반복이 우연히 겹친 것으로 확인(위 참고)
- [보류·차단] beam-circular 어댑터 반환 타입 버그 — `gh` CLI 미설치로 이슈 미등록, 초안만 작성([beam_circular_adapter_issue_draft.md](beam_circular_adapter_issue_draft.md))
- [보류] 후보 임계값(30/45/60/75/90/120) 민감도 분석, 사용자 행동 데이터 기반 검증
