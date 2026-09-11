from pathlib import Path

# 경로
BENCH_DIR = Path(__file__).resolve().parent
DATASETS_DIR = BENCH_DIR / "datasets"
FIXTURES_DIR = BENCH_DIR / "fixtures"
RESULTS_DIR  = BENCH_DIR / "results"

# 기본 입력 파일
ROUTE_NODES_PARQUET  = FIXTURES_DIR / "route_nodes.parquet"  # 도보 그래프 노드
ROUTE_EDGES_PARQUET  = FIXTURES_DIR / "route_edges.parquet"  # 도보 그래프 엣지
ROUTE_ENGINE_DATASET = DATASETS_DIR / "route_engine.json"    # 테스트 데이터셋

# 경로 엔진 알고리즘 성능 테스트 시 필요한 상수
LENGTH_TOLERANCE = 0.10  # ±10% 오차 범위
LATENCY_REPEAT   = 5     # latency 측정 시, 반복 횟수

# ── 순환 경로 합격 게이트 (2026-09-10) ──────────────────────────────────────
# 게이트는 "최종 경로에서 직접 관측되는 값"만 쓴다. 경유지는 사용자와 약속한 대상이
# 아니라 순환 경로를 만들기 위한 내부 수단이므로, 경유지 분해에 의존하는 지표
# (waypoint_separation_m, segment_balance_ratio, is_degenerate_loop, feasible,
#  effective_waypoints_used)는 게이트에 넣지 않는다 — 전부 진단으로만 쓴다.
# 판정 본체는 benchmarks/results.py::evaluate_gate() 참고.
#
# ── 임계값 확정 시도 결과 (2026-09-11 기록) ────────────────────────────────
# 이전 주석은 "1차 격자 실행 후 분포를 보고 확정하고, 그때 이 주석도 함께 갱신할 것"이라고
# 약속했다. 격자는 돌았다(2026-09-10, geometry_validation_results.csv 500행 = 출발지 5 ×
# target_km {3.0, 5.0} × 시드 10 × 알고리즘 5). 결과는 "이 데이터로는 확정할 수 없다"이다.
# 같은 분석을 반복하지 않도록 왜 못 했는지를 남긴다.
#
# 실측 분포(500행):
#   spike_count            : 500/500이 0
#   repeated_edge_ratio    : 최댓값 0.2387 (알고리즘별 평균 0.0006~0.0131) — 0.35에 한참 못 미침
#   distance_deviation_km  : 게이트 탈락 10건이 전부 레거시 GRASP+VNS. wp 계열 최댓값은 0.246
#
# 확정하지 못한 이유: 현재 격자에 **퇴화 사례가 없다**. analyze_thresholds.py의 후보 스윕
# (results/threshold_degenerate_sweep.csv)에서 임계값 0.25 이상은 플래그 0건, 0.10까지
# 낮춰도 1건(0.2%)이라 "이 임계값이 나쁜 경로를 골라내는가"를 잴 표본 자체가 없다.
# 퇴화 사례가 포함된 격자가 있어야 하고, 그것은 시나리오 데이터셋 개편에 달려 있다(별도 이슈).
#
# ⚠ 다만 "전부 통과"가 곧 결함은 아니다. 세 값의 역할이 서로 다르다:
#   - MAX_SPIKE_COUNT / MAX_REPEATED_EDGE_RATIO : 회귀 감시 + prune_dead_ends 개편 대비용.
#     정상 동작에서 전 행 통과하는 것이 정상이며, 개편으로 값이 움직이기 시작할 때
#     비로소 구속력을 갖는다. 지금 임계값을 관측 분포에 맞춰 조이면 감시 기능이 죽는다.
#   - MAX_DISTANCE_DEVIATION_KM : 실제로 판정을 가르는 유일한 항목이지만, 가른 대상이
#     레거시 대 wp 계열뿐이라 wp 계열 내부를 구분하지는 못한다.
#
# 그래서 게이트는 우열 판정이 아니라 참가 자격으로만 쓴다 — 순위 규칙은
# aggregate_results.py 모듈 docstring 참고(2026-09-11 변경).
# 재현: python -m benchmarks.analyze_thresholds benchmarks/geometry_validation_results.csv
MAX_DISTANCE_DEVIATION_KM = 0.5   # 목표 3km에서 ±0.5km. LENGTH_TOLERANCE(±10%)보다 느슨하게 시작
MAX_REPEATED_EDGE_RATIO = 0.35    # 엔진의 퇴화 판정 임계값(_DEGENERATE_REPEATED_EDGE_RATIO)과 동일값
MAX_SPIKE_COUNT = 0               # prune_dead_ends를 거친 경로라면 0이어야 한다

# ── 다중 조건 격자 공용 상수 (2026-09-10) ──────────────────────────────────
# 러너 4종이 각자 SEEDS = [42, 7, 123]을 들고 있었다. 시드 3개는 표준편차 추정
# 표본으로 부족해(자유도 2) 확률적 알고리즘의 분산·최악값을 논할 수 없다.
# 10개로 늘리고 한 곳에서 관리한다 — 저장소 안에 이미 10-시드 선례가 있다
# (benchmarks/runner/waypoint_overlap_audit.py의 alns_seeds=list(range(10))).
BENCHMARK_SEEDS = [42, 7, 123, 2026, 11, 305, 88, 1717, 64, 909]

# 격자 러너가 params에 넣을 사용자 체감 허용시간(초). 지금까지 러너들이 이 값을
# 넣지 않아 within_time_budget이 전 행 None이었고, 제품 관점의 지연 허용선이
# 알고리즘 결정에 전혀 반영되지 않았다.
#
# 5.0 → 60.0 확정 근거(2026-09-11 사용자 결정):
#   경로 생성은 (1) 동기 요청-응답이고 (2) 대화가 모두 끝난 뒤 실행되는 목표 달성
#   시점의 대기이며 (3) 진행 표시를 전제한다. Nielsen(1993, Usability Engineering)의
#   10초 한계는 "아무 피드백 없는 대기"의 기준이라 이 맥락에는 적용되지 않는다.
#   숫자를 실측에 맞춰 올린 것이 아니라 맥락에서 허용 범위를 먼저 정한 값이다 —
#   실제로 60초로 올려도 결론은 바뀌지 않는다(2026-09-10 실측: GRASP-Waypoint+VNS
#   생존율 0.18, +ALNS 0.55로 여전히 비교 불가, 실용 후보는 +Local 그대로).
#
# ⚠ 주의: 이 값은 엔진이 읽지 않는다. src/route_engine 어디에도 time_budget_sec를
#   참조하는 코드가 없고, benchmarks/results.py가 elapsed_sec과 비교해 라벨
#   (within_time_budget)을 붙일 뿐이다. 따라서 이 숫자를 바꿔도 알고리즘 동작은
#   변하지 않는다 — 엔진이 예산 안에서 최선해를 반환하게 하려면 별도 작업이 필요하다.
# ⚠ 인프라 상한 미확인: 동기 요청이므로 리버스 프록시·LB 타임아웃(nginx
#   proxy_read_timeout 기본 60초)이 실제 상한을 먼저 정할 수 있다. 배포 구성 확인 필요.
DEFAULT_TIME_BUDGET_SEC = 60.0

# 파레토 전선에 함께 긋는 참고 예산선(초). 예산이 재논의돼도 격자를 다시 돌리지 않고
# 표만 다시 읽으면 되도록, 후보 구간을 한 번에 산출한다.
TIME_BUDGET_REFERENCE_SEC = (5.0, 10.0, 20.0, 60.0)

# cutoff SSSP 1회를 A* 경로 조회 몇 회로 환산할지(계산량 단위 통일용).
#
# 근거(2026-09-10 실측 500행, benchmarks/geometry_validation_results.csv 회귀):
#   elapsed_sec ~ a·(astar_calls + cache_hits) + b·pool_cache_misses, 절편 없음
#   a = 1.47ms/조회, b = 40.3ms/SSSP → b/a = 27.5
#   설명력 R² = 0.686. astar_calls 단독 모델은 R² = 0.238에 그친다.
# 두 카운터는 서로 다른 연산이다 — pool_cache_miss 1회는 waypoint_pool.py의
# single_source_dijkstra_path_length(cutoff=r_max) 1회이고, A* 1회와 단위가 같지 않다.
# ⚠ 6워커 병렬 풀에서 잰 값이라 환경 의존적이다. 노드 확장 수(heap pop)를 직접 계측하면
#   이 환산 계수 자체가 필요 없어진다 — 그쪽이 근본 해법이다.
SSSP_TO_LOOKUP_RATIO = 27.5

# 서울 도보망에서 관측된 circularity_q의 최댓값 범위(2026-09-10, 출발지 5개 ×
# target_km {3.0, 5.0} 10개 조건). 조건별 관측 최대 Q가 0.572~0.708에 모인다.
# 완전한 원(Q=1)은 도보망에서 불가능하므로 이 값은 "달성 가능 상한의 실측 하한선"이며,
# Q=0.47은 상한 대비 약 70%로 읽어야 한다.
# ⚠ 이론 상한이 아니다. 조건별 이상적 원에 가장 가까운 도보 경로를 따로 구해야 이론
#   상한에 접근하며, 그 자체가 별도 알고리즘 문제라 아직 하지 않았다.
OBSERVED_CIRCULARITY_Q_MAX_RANGE = (0.572, 0.708)

# 순환 경로 격자에서 고정할 스코어링 프로필.
# wp 계열(grasp-wp-*/beam-wp-*)은 mode="distance" 고정이라 profile을 아예 읽지 않는
# 반면 레거시 grasp-circular/beam-circular는 반영한다. 시나리오 데이터셋의 5개
# 프로필을 그대로 쓰면 두 진영이 서로 다른 목적함수를 최적화한 채 나란히 비교돼
# 결론이 성립하지 않으므로, 순환 비교에서는 이 값으로 고정한다.
# (편도는 프로필을 정상적으로 쓰므로 시나리오 값을 그대로 둔다.)
CIRCULAR_BENCHMARK_PROFILE = "default"