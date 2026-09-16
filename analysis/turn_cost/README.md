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

`grasp-wp-alns`/`beam-wp-alns`/`beam-wp-vns` 3종은 §"seed 반복 측정" 결과(25개 시나리오 × 시드 10개, n=250)로 **보정된 평균값**이다(★). 나머지 6종은 결정적 엔진이라 seed=42 단일 실행값 그대로다. p50/p90/45~90°↑ 열은 아직 seed=42 단일 실행 기준이라 ★ 엔진 3종에는 참고용으로만 남겨둔다(보정 전 값).

| 엔진 | 평균 총회전량(°) | p50(°) | p90(°) | 평균 최대회전각(°) | 평균 거리당회전량(°/km) | 45°↑ | 60°↑ | 90°↑ |
|---|---|---|---|---|---|---|---|---|
| grasp-wp-vns | 2667.1 | 2431.9 | 3852.5 | 119.5 | **740.7** | 26.4 | 21.6 | 7.7 |
| beam-wp-local | 2751.9 | 2918.8 | 3646.1 | 125.8 | **789.3** | 27.7 | 23.3 | 7.1 |
| beam-wp-vnd | 2791.1 | 2918.8 | 3706.8 | 126.2 | **792.3** | 28.0 | 24.0 | 7.8 |
| beam-wp-alns ★ | 2706.4 | — | — | 133.9 | **793.0** (SEM 12.5) | — | — | — |
| beam-wp-vns ★ | 2821.3 | — | — | 128.8 | **794.6** (SEM 14.7) | — | — | — |
| grasp-wp-alns ★ | 2859.4 | — | — | 128.2 | **796.7** (SEM 10.7) | — | — | — |
| beam-wp | 2780.4 | 2563.9 | 4114.2 | 158.0 | **797.5** | 27.5 | 22.6 | 6.9 |
| grasp-wp-local | 2865.9 | 2737.1 | 4064.5 | 126.1 | **800.7** | 28.8 | 24.7 | 8.5 |
| grasp-wp-vnd | 2874.8 | 2958.9 | 4064.5 | 126.1 | **803.3** | 29.0 | 24.9 | 8.6 |

**전체 candidate_turn_count 19,396건 중 undefined 0건(0.000%)** — 좌표 누락·0길이 벡터 등 정의 불가 케이스가 이 데이터셋에서는 발생하지 않았다. 다만 이는 "이번 데이터셋에 없었다"는 것이지, 방어 로직(`undefined_turn_reasons` 집계)을 제거해도 된다는 뜻이 아니다 — 단위 테스트와 방어 로직은 유지한다.

**9종 간 편차는 크지 않다** — 거리당 회전량 기준 최소(740.7)~최대(803.3)가 1.09배 차이로, 서로 회전 형태 면에서 꽤 비슷하다.

## seed 반복 측정 — `beam-wp-vns`의 순위가 완전히 뒤집힌다

`grasp-wp-alns`/`beam-wp-alns`/`beam-wp-vns` 3종은 [반복 실행 분산 확인](#반복-실행-분산-확인-variance_sample) 절에서 seed에 따라 실제로 값이 크게 달라짐을 확인했다. 이 3종을 대표할 수 있는 값을 얻기 위해 `benchmarks/config.py::BENCHMARK_SEEDS`(팀이 이미 분산 추정용으로 정해둔 시드 10개)로 25개 시나리오 전수를 다시 측정했다(750회 시도, 750/750 성공). 결과: [seed_repeat_results.csv](seed_repeat_results.csv), 스크립트: [seed_repeat_check.py](seed_repeat_check.py).

| 엔진 | 평균 거리당회전량(°/km, n=250) | 표준편차 | 최소~최대 | 95% 신뢰구간 | seed=42 단일값(기존 표) |
|---|---|---|---|---|---|
| beam-wp-alns | 793.0 | 196.95 | 489.1 ~ 1474.2 | [768.6, 817.4] | 788.0 (거의 동일) |
| beam-wp-vns | 794.6 | 232.63 | 272.9 ~ 1670.9 | [765.7, 823.4] | **845.4 (6.4% 높게 관측됨)** |
| grasp-wp-alns | 796.7 | 169.33 | 338.6 ~ 1374.1 | [775.7, 817.7] | 795.7 (거의 동일) |

**핵심 발견**: `beam-wp-vns`는 seed=42 단일 실행에서 845.4°/km로 **9종 중 최하위(가장 나쁨)**로 나왔었는데, 10개 시드 평균으로는 794.6°/km로 **중위권(9종 중 5위)**이다. 단일 시드 관측값이 우연히 나쁜 쪽으로 치우쳐 있었던 것이다.

**더 중요한 발견**: 세 엔진의 95% 신뢰구간이 서로 완전히 겹치고, 심지어 결정적 엔진들(`beam-wp-local` 789.3, `beam-wp-vnd` 792.3, `beam-wp` 797.5, `grasp-wp-local` 800.7, `grasp-wp-vnd` 803.3)의 값도 대부분 이 신뢰구간 안에 들어온다. **즉 `grasp-wp-vns`(740.7, 신뢰구간 밖) 하나만 확실히 다르고, 나머지 8종은 거리당 회전량만으로는 서로 통계적으로 구분하기 어렵다.** 원래 표의 세밀한 순위(2~9위 사이 소수점 차이)는 노이즈 수준의 차이였을 가능성이 높다.

**한계**: 반복은 `turn_deg_per_km`/`total_turn_deg`/`max_turn_deg`만 다시 계산했다 — p50/p90/45~90°↑ 열까지 10개 시드로 다시 구하려면 원본 회전각까지 저장하는 추가 실행이 필요해 이번에는 하지 않았다.

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

**해석**: "seed를 읽는 코드가 있다"는 것과 "실제로 결과가 바뀐다"는 것은 다르다. `grasp-wp-alns`(항상)와 `beam-wp-vns`/`beam-wp-alns`(시나리오에 따라, 가끔 크게)는 seed=42 단일 실행값을 그 엔진의 대표값으로 쓸 수 없었다 — 특히 `beam-wp-alns`는 한 시나리오에서 1.76배(1901.6→3342.3) 차이가 났다. 반면 나머지 5종(+`beam-wp`)은 이번 표본에서는 seed=42 단일 실행값을 그대로 신뢰해도 큰 문제가 없어 보인다. **이 3종에 대한 25개 시나리오 전수·10개 시드 보정값은 아래 "seed 반복 측정" 절 참고 — 위 "엔진별 회전량 통계" 표에 이미 반영했다.**

*(초기 집계에서 "9개 조합 통합 std"를 한 표로 냈었는데, 이는 시나리오 간 기저값 차이(거리·경로 길이가 다름)와 seed로 인한 변동을 한데 섞어 오해를 부를 수 있어 폐기했다 — 시나리오별로 나눈 위 표만 신뢰할 것.)*

## 한계

1. **주 분포 표의 6종(결정적 엔진)은 각 엔진 1회 실행(seed=42 고정) 결과다.** `grasp-wp-alns`/`beam-wp-alns`/`beam-wp-vns` 3종은 seed 반복 측정(10개 시드 × 25개 시나리오, n=250)으로 보정했다 — 아래 "seed 반복 측정" 절 참고. 보정 결과, 9종 중 8종의 거리당 회전량은 95% 신뢰구간이 서로 겹쳐 통계적으로 뚜렷이 구분되지 않는다(`grasp-wp-vns`만 확실히 낮음).
2. **45°/60°/90° 임계값은 보편적 보행 불편 기준이 아니라 잠정 운영 임계값이다.**
3. **회전량을 엔진 선택의 목적함수에 연결하지 않았다** — 진단·비교용으로만 사용.
4. p50/p90/45~90°↑ 등 세부 열은 아직 seed=42 단일 실행 기준이다 — 이 열들까지 다중 시드로 보정하려면 원본 회전각까지 저장하는 추가 실행이 필요하다(하지 않음).

## 임계값(30/45/60/75/90/120°) 민감도 분석

`turn_count_ge_*` 계열은 아직 검증된 인간공학적 기준이 아니라 잠정 운영 임계값이다(README 상단 "한계" 참고). 여기서는 "이 후보 임계값들 중 하나를 골라도 결과가 안정적인가"만 확인한다 — 실제 보행 속도·주관적 불편도 등 사용자 행동 데이터와의 상관관계 검증은 별도 작업(보류)이다.

### 전체 회전각 분포 (19,396건, 9개 엔진 × 25개 시나리오 통합)

| 백분위수 | 값(도) |
|---|---|
| p50 | 11.9 |
| p75 | 66.0 |
| p90 | 89.3 |
| p95 | 93.9 |
| p99 | 114.9 |

| 임계값 | 이 각도 이상인 회전의 비율 |
|---|---|
| 30° | 38.1% |
| 45° | 32.4% |
| 60° | 27.4% |
| 90° | 9.1% |
| 120° | 0.68% |

**실측 맥락**: 45°는 실제로 전체 회전의 1/3가량이 넘는 흔한 수준이라 "급회전"이라 부르기엔 약하고, 90°는 약 11번에 1번꼴로 나오는 수준, 120°는 150번에 1번꼴로 나오는 뚜렷한 극단값이다. 즉 이 6개 후보 중 "무엇을 급회전으로 볼지"는 정의에 따라 완전히 다른 빈도를 가리킨다.

### 임계값에 따라 엔진 순위가 실제로 바뀐다

임계값별로 "해당 각도 이상 회전이 적은 순"으로 9개 엔진을 줄 세우면:

```
30°  : grasp-wp-vns < beam-wp-alns < beam-wp < beam-wp-local < beam-wp-vnd < grasp-wp-local < grasp-wp-vnd < grasp-wp-alns < beam-wp-vns
45°  : grasp-wp-vns < beam-wp-alns < beam-wp < beam-wp-local < beam-wp-vnd < grasp-wp-alns  < grasp-wp-local < grasp-wp-vnd < beam-wp-vns
60°  : grasp-wp-vns < beam-wp-alns < beam-wp < beam-wp-local < beam-wp-vnd < grasp-wp-alns  < grasp-wp-local < grasp-wp-vnd < beam-wp-vns
75°  : beam-wp-alns < beam-wp-local < beam-wp < grasp-wp-vns < beam-wp-vnd < grasp-wp-alns  < grasp-wp-local < grasp-wp-vnd < beam-wp-vns
90°  : beam-wp      < beam-wp-local < beam-wp-alns < grasp-wp-vns < beam-wp-vnd < grasp-wp-alns < grasp-wp-local < grasp-wp-vnd < beam-wp-vns
120° : grasp-wp-vns < beam-wp-local < beam-wp-vnd < beam-wp-alns < grasp-wp-alns < beam-wp-vns < grasp-wp-local < grasp-wp-vnd < beam-wp
```

- **30~60°는 서로 순위가 거의 같다**(상위 5개 순서 동일, 하위권만 약간 뒤바뀜) — 완만~보통 회전 기준으로는 결론이 안정적이다.
- **75~90°부터 순위가 크게 흔들린다**: `beam-wp`가 30~60° 기준으로는 3위(중위권)인데 90° 기준으로는 **1위(급회전 최소)**로 뛰어오른다.
- **120°에서는 `beam-wp`가 정반대로 9위(최하위, 0.88회)**로 떨어진다 — 30~90° 기준으로는 계속 상위~중위권이었는데, 가장 극단적인 회전(120° 이상)만 보면 오히려 가장 많다.

**해석**: `beam-wp`는 "어지간한 급회전(90° 안팎)은 잘 안 만들지만, 아주 가끔 만드는 회전은 유난히 극단적으로 크다"는 성격이다(앞서 확인한 "평균 최대 단일회전각이 9종 중 가장 큼(158.0°)"과 정확히 들어맞는다). **어떤 임계값을 "급회전 기준"으로 채택하느냐에 따라 `beam-wp`에 대한 평가가 정반대로 뒤집힐 수 있다** — 이건 특정 임계값 하나로 엔진을 확정 비교해서는 안 된다는 걸 데이터로 보여주는 사례다.

### 결론

1. 완만~보통 회전(30~60°) 판단은 임계값 선택에 크게 민감하지 않다.
2. 급회전(75° 이상) 판단은 임계값 선택에 따라 순위가 크게 달라질 수 있어, **하나의 임계값으로 "이 엔진이 급회전이 적다"고 단정하면 안 된다.**
3. 이 분석은 엔진 간 순위의 안정성만 확인했을 뿐, 45/60/90/120° 중 어느 것이 실제 보행 불편과 상관관계가 있는지는 여전히 검증되지 않았다 — 사용자 행동 데이터 기반 검증은 계속 보류 상태다.

## 다음 단계

- [완료] 현재 활성 엔진 9종으로 25개 시나리오 전수 측정
- [완료] `grasp-wp-vnd` == `grasp-wp-local` 경로 동일 현상 원인 조사 — 버그 아님(위 참고)
- [완료] 반복 실행 분산 확인 — `grasp-wp-alns`/`beam-wp-alns`/`beam-wp-vns`는 seed에 따라 실제로 변동함을 확인(위 참고)
- [완료] `grasp-wp-alns`/`beam-wp-alns`/`beam-wp-vns` 25개 시나리오 × 10개 시드 재측정 — `beam-wp-vns`가 최하위(845.4)에서 중위권(794.6)으로 순위가 뒤집힘, 8종은 통계적으로 뚜렷이 구분 안 됨(위 "seed 반복 측정" 절 참고)
- [완료] 후보 임계값(30/45/60/75/90/120) 민감도 분석 — 30~60°는 순위 안정적, 75° 이상부터 순위가 크게 흔들림(위 참고)
- [보류] 사용자 행동 데이터 기반 검증(실제 보행 속도·주관적 불편도와의 상관관계) — 데이터 자체가 없어 계속 보류
