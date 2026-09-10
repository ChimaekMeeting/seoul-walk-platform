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
# ⚠ 아래 세 값은 아직 실측으로 확정되지 않은 1차 실험값이다. 1차 격자 실행 후
#   분포를 보고 확정하고, 그때 이 주석도 함께 갱신할 것(이슈 D·I).
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
# ⚠ 미확정 실험값 — 실제 UX 기준이 정해지면 갱신할 것.
DEFAULT_TIME_BUDGET_SEC = 5.0

# 순환 경로 격자에서 고정할 스코어링 프로필.
# wp 계열(grasp-wp-*/beam-wp-*)은 mode="distance" 고정이라 profile을 아예 읽지 않는
# 반면 레거시 grasp-circular/beam-circular는 반영한다. 시나리오 데이터셋의 5개
# 프로필을 그대로 쓰면 두 진영이 서로 다른 목적함수를 최적화한 채 나란히 비교돼
# 결론이 성립하지 않으므로, 순환 비교에서는 이 값으로 고정한다.
# (편도는 프로필을 정상적으로 쓰므로 시나리오 값을 그대로 둔다.)
CIRCULAR_BENCHMARK_PROFILE = "default"