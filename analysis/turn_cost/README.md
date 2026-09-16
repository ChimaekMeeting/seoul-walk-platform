# turn_cost 경로 형상 분포 — 탐색적 1차 관측

> **주의**: 이 폴더의 결과는 **확정된 결론이 아니라 탐색적(exploratory) 1차 관측**입니다.
> 반복 측정 없이 각 엔진 1회 실행만 수행했습니다. 엔진 우열이나 보행 편안함의
> 확정 근거로 인용하지 마세요.

## 실행 정보

| 항목 | 내용 |
|---|---|
| 실행일 | 2026-09-16 |
| 코드 기준 | `feature/turn-cost-metric` = `dev`(`331cad6`) + turn_cost 작업 병합 후 |
| 그래프 | 서울 도보 그래프 fixture(160,328노드 / 223,927엣지) |
| 시나리오 | `benchmarks/datasets/route_engine.json`의 순환 시나리오 25개(전수) |
| 엔진 | `run_all_scenarios.py::CIRCULAR_ALGOS` 9종(현재 `SOLVER_REGISTRY`의 순환 엔진 전체) — `grasp-wp-local/vnd/vns/alns`, `beam-wp`, `beam-wp-local/vnd/vns/alns` |
| seed | 42(각 solver `_DEFAULT_SEED`와 동일, 명시적으로 고정) |
| 스크립트 / 원본 결과 | [turn_cost_distribution_check.py](turn_cost_distribution_check.py) / [turn_cost_distribution.csv](turn_cost_distribution.csv) |
| 성공률 | **225/225 (25×9 전부 성공, 실패 0건)** |
| 총 소요시간 | 3,972초(약 66분) |

## 지표 정의

- `total_turn_deg`: 경로 전체의 누적 방향 변화(회전각의 절대값 합, 도)
- `turn_deg_per_km`: `total_turn_deg`를 실제 이동 거리(km)로 정규화한 값
- `max_turn_deg`: 경로 내 가장 큰 단일 회전각
- `turn_count_ge_45/60/90`: 해당 각도 이상인 회전의 개수(잠정 운영 임계값 — 보편적 보행 불편 기준 아님)
- `undefined_turn_count`: 좌표 누락·0길이 벡터 등으로 정의할 수 없었던 회전 지점 수

## 엔진별 회전량 통계 (거리당 회전량 오름차순)

| 엔진 | 평균 총회전량(°) | p50(°) | p90(°) | 평균 최대회전각(°) | 평균 거리당회전량(°/km) | 45°↑ | 60°↑ | 90°↑ |
|---|---|---|---|---|---|---|---|---|
| grasp-wp-vns | 2667.1 | 2431.9 | 3852.5 | 119.5 | **740.7** | 26.4 | 21.6 | 7.7 |
| beam-wp-alns | 2685.4 | 2824.7 | 3581.3 | 133.8 | **788.0** | 26.6 | 22.4 | 7.1 |
| beam-wp-local | 2751.9 | 2918.8 | 3646.1 | 125.8 | **789.3** | 27.7 | 23.3 | 7.1 |
| beam-wp-vnd | 2791.1 | 2918.8 | 3706.8 | 126.2 | **792.3** | 28.0 | 24.0 | 7.8 |
| grasp-wp-alns | 2868.7 | 2910.7 | 3847.5 | 132.3 | **795.7** | 28.1 | 24.2 | 7.9 |
| beam-wp | 2780.4 | 2563.9 | 4114.2 | 158.0 | **797.5** | 27.5 | 22.6 | 6.9 |
| grasp-wp-local | 2865.9 | 2737.1 | 4064.5 | 126.1 | **800.7** | 28.8 | 24.7 | 8.5 |
| grasp-wp-vnd | 2874.8 | 2958.9 | 4064.5 | 126.1 | **803.3** | 29.0 | 24.9 | 8.6 |
| beam-wp-vns | 2949.2 | 2979.9 | 3803.1 | 131.9 | **845.4** | 29.6 | 25.0 | 8.9 |

**전체 candidate_turn_count 19,396건 중 undefined 0건(0.000%)** — 좌표 누락·0길이 벡터 등 정의 불가 케이스가 이 데이터셋에서는 발생하지 않았다. 다만 이는 "이번 데이터셋에 없었다"는 것이지, 방어 로직(`undefined_turn_reasons` 집계)을 제거해도 된다는 뜻이 아니다 — 단위 테스트와 방어 로직은 유지한다.

**9종 간 편차는 크지 않다** — 거리당 회전량 기준 최소(740.7)~최대(845.4)가 1.14배 차이로, 서로 회전 형태 면에서 꽤 비슷하다.

## 지표 간 순위 불일치 (중요 — 단일 지표로 대체하지 말 것)

`total_turn_deg`/`turn_deg_per_km`(누적 방향 변화)과 `max_turn_deg`/`turn_count_ge_90`(급회전 패턴)은 **서로 다른 현상을 측정**하며, 실제로 순위가 갈린다.

```
turn_deg_per_km 순위(완만한 순):
  grasp-wp-vns < beam-wp-alns < beam-wp-local < beam-wp-vnd < grasp-wp-alns
  < beam-wp < grasp-wp-local < grasp-wp-vnd < beam-wp-vns

turn_count_ge_90 순위(급회전 적은 순):
  beam-wp < beam-wp-local < beam-wp-alns < grasp-wp-vns < beam-wp-vnd
  < grasp-wp-alns < grasp-wp-local < grasp-wp-vnd < beam-wp-vns

max_turn_deg 순위(최대 단일회전 작은 순):
  grasp-wp-vns < beam-wp-local < grasp-wp-local < grasp-wp-vnd < beam-wp-vnd
  < beam-wp-vns < grasp-wp-alns < beam-wp-alns < beam-wp
```

`beam-wp`가 대표적 예다 — 거리당 회전량은 중위권(6위)인데, **급회전(90°↑) 횟수는 9종 중 가장 적고(6.9회)**, 동시에 **평균 최대 단일회전각은 가장 크다(158.0°)**. 즉 `beam-wp`는 "크게 한 번씩 꺾이지만 잦은 급회전은 없는" 유형이고, 반대로 `beam-wp-vns`는 거리당 회전량·급회전 횟수 모두 최하위(가장 나쁨)다.

**결론**: 누적 회전량 지표와 급회전 지표는 함께 보고해야 하며, 하나로 대체할 수 없다.

## 조사 완료: `grasp-wp-vnd` == `grasp-wp-local` 경로 동일 현상

25개 시나리오 중 일부에서 `grasp-wp-vnd`의 결과가 `grasp-wp-local`과 노드ID까지 완전히 일치하는 사례가 있어, 실제 `vnd()`/`_local_search()` 메서드를 GRASP 반복(`grasp_iters=24`) 단위로 직접 호출해 비교했다(`circular_20` 기준).

**결론: 버그가 아니다.** 다음이 모두 코드로 직접 확인됐다.

- **VND는 실제로 실행되고 실제로 개선한다**: 24회 반복 중 9회에서 VND가 Local과 다른(그리고 목적함수 기준 명백히 더 나은) 경로를 만들었다. 예: 반복 0에서 Local은 `distance_error=84.4m, repeated_edge_ratio=0.122`, VND는 `distance_error=60.8m, repeated_edge_ratio=0.045`.
- **다만 "최종 채택 반복"이 우연히 겹쳤다**: GRASP은 24회 중 하나만 최종 채택하는데, 채택 기준(`RouteObjective.sort_key()`)이 `repeated_edge_ratio`(자기중첩)를 `distance_error_m`(거리 오차)보다 **우선** 순위로 둔다. 이 시나리오에서는 반복 1번(`repeated_edge_ratio=0.033`)이 최종 승자였는데, 하필 반복 1번은 VND가 추가 개선을 못 찾은(=Local과 이미 같은) 9회 중 하나가 아니었다. VND가 다른 22개 반복에서는 분명히 더 나은 경로를 찾았지만, 그중 어느 것도 반복 1번의 낮은 `repeated_edge_ratio`를 이기지 못해 최종 결과만 우연히 같아진 것이다.
- **호출 경로·어댑터 버그 없음**: `SOLVER_REGISTRY`가 서로 다른 클래스(`CircularGraspWaypointLocalEngine`/`CircularGraspWaypointVndEngine`)를 정확히 가리키며, 결과를 덮어쓰는 코드도 없다.

**일반화 주의**: 이건 `seed=42`·`rcl_size=8`·`grasp_iters=24`라는 특정 설정과 "자기중첩 최소화를 거리 정확도보다 우선"하는 목적함수 설계가 겹쳐 생긴 관측이다. 다른 시나리오·시드에서는 VND가 Local을 실제로 앞지르는 결과가 나올 수 있다 — "VND와 Local이 항상 같다"고 일반화하면 안 된다.

## 반복 실행 분산 확인 (`variance_sample/`)

대표 시나리오 3개(짧음/중간/김: `circular_20`/`circular_11`/`circular_01`) 기준, `benchmarks/benchmark.py::SEED_SENSITIVE_SOLVERS`가 seed를 실제로 읽는다고 분류한 8종은 **서로 다른 seed 3개(42/7/123)**로 실행했고(같은 프로세스 반복이 아니라 진짜 값을 바꿔서), 그 목록에서 빠진 `beam-wp`는 결정성만 2회 재확인했다. 결과: [variance_results.csv](variance_sample/variance_results.csv), 스크립트: [variance_check.py](variance_sample/variance_check.py).

**엔진별: 3개 시나리오 중 seed에 따라 값이 실제로 달라진 시나리오 수**

| 엔진 | 값이 달라진 시나리오 수 | 비고 |
|---|---|---|
| grasp-wp-alns | 3/3 | 모든 시나리오에서 seed에 따라 변동 — 진짜 확률적 |
| beam-wp-vns | 2/3 | |
| beam-wp-alns | 1/3 | 그 1개(`circular_11`)에서 총회전량이 1901.6~3342.3(°)으로 **크게 흔들림** |
| beam-wp-local / beam-wp-vnd / grasp-wp-local / grasp-wp-vnd / grasp-wp-vns | 0/3 | 코드상 seed-sensitive로 분류돼 있지만, 테스트한 3개 시나리오에서는 seed를 바꿔도 결과가 동일했다(실질적으로 결정적) |
| beam-wp(seed 미참조) | — | 2회 반복 모두 3개 시나리오에서 완전히 동일 — 결정성 재확인 |

**해석**: "seed를 읽는 코드가 있다"는 것과 "실제로 결과가 바뀐다"는 것은 다르다. `grasp-wp-alns`(항상)와 `beam-wp-vns`/`beam-wp-alns`(시나리오에 따라, 가끔 크게)는 **위 "엔진별 회전량 통계" 표의 값(seed=42 단일 실행)을 그 엔진의 대표값으로 단정하면 안 된다** — 특히 `beam-wp-alns`는 한 시나리오에서 1.76배(1901.6→3342.3) 차이가 났다. 반면 나머지 5종(+`beam-wp`)은 이번 표본에서는 seed=42 단일 실행값을 그대로 신뢰해도 큰 문제가 없어 보인다.

*(초기 집계에서 "9개 조합 통합 std"를 한 표로 냈었는데, 이는 시나리오 간 기저값 차이(거리·경로 길이가 다름)와 seed로 인한 변동을 한데 섞어 오해를 부를 수 있어 폐기했다 — 시나리오별로 나눈 위 표만 신뢰할 것.)*

## 한계

1. **주 분포 표(엔진별 회전량 통계)는 각 엔진 1회 실행(seed=42 고정) 결과다.** 분산 확인 결과 `grasp-wp-alns`/`beam-wp-alns`/`beam-wp-vns` 3종은 seed에 따라 실제로 값이 크게 바뀔 수 있어, 이 3종의 표 값은 "대표값"이 아니라 "seed=42에서의 관측값 하나"로만 봐야 한다. 나머지 6종(`beam-wp` 포함)은 테스트한 범위에서 seed 영향이 없었다.
2. **45°/60°/90° 임계값은 보편적 보행 불편 기준이 아니라 잠정 운영 임계값이다.**
3. **회전량을 엔진 선택의 목적함수에 연결하지 않았다** — 진단·비교용으로만 사용.
4. 분산 확인은 대표 시나리오 3개 × seed 3개로 한정된 표본이다 — 더 많은 시나리오·seed로 확장하면 다른 엔진에서도 변동이 발견될 수 있다.

## 다음 단계

- [완료] 현재 활성 엔진 9종으로 25개 시나리오 전수 측정
- [완료] `grasp-wp-vnd` == `grasp-wp-local` 경로 동일 현상 원인 조사 — 버그 아님(위 참고)
- [완료] 반복 실행 분산 확인 — `grasp-wp-alns`/`beam-wp-alns`/`beam-wp-vns`는 seed에 따라 실제로 변동함을 확인(위 참고)
- [후속 권장] `grasp-wp-alns`/`beam-wp-alns`/`beam-wp-vns`는 25개 시나리오 전수를 여러 seed로 반복해 평균·분산을 반영한 값으로 위 "엔진별 회전량 통계" 표를 다시 산출할 필요가 있다(현재 표는 이 3종에 한해 대표성이 약함)
- [보류] 후보 임계값(30/45/60/75/90/120) 민감도 분석, 사용자 행동 데이터 기반 검증
