"""
benchmarks/run_min_separation_validation.py

P2-P3 최소거리 안전장치("Claude CLI 전달용 구현 지시서: 현재 구현을 유지한 상태에서
P2-P3 최소거리와 추가 검증만 반영", 2026-08-30) §7이 요구하는 다중 조건 검증 러너.

seed × target_km × start_node 조합마다 grasp-wp-local/vnd/vns를 동일 조건에서 실행하고
(비교 기준이던 grasp-circular는 2026-09-11 레지스트리에서 제외),
결과를 원본 CSV(반올림 없는 값 그대로)로 저장한다. run_all_scenarios.py
와 달리 고정 시나리오 데이터셋(JSON)이 아니라 이 스크립트 자체가 정의하는 seed/target_km/
start_node 격자를 순회한다.

범위 축소 근거(요청서 §7 "가능하면 7km"는 선택 사항으로 명시돼 있음):
    target_km=7.0은 생략했다 — VNS가 target_km=5.0 1회에 약 230~250초가 걸려(2026-08-30
    실측), 7km까지 포함하면 전체 매트릭스가 감당하기 어려운 시간으로 늘어난다. 대신
    target_km=3.0/5.0에서 먼저 안정성을 확인하고, 필요하면 7km는 별도로 추가 실행한다.

실행:
    python -m benchmarks.run_min_separation_validation
"""

import multiprocessing
import time

import pandas as pd

from benchmarks.benchmark import _load_default_graph, SOLVER_REGISTRY
from benchmarks.config import BENCHMARK_SEEDS, DEFAULT_TIME_BUDGET_SEC
from benchmarks.results import RESULT_COLUMNS, failed_row, run_solver_task
from benchmarks.run_metadata import save_run_metadata
from src.route_engine.scoring.scoring_engine import precompute_scoring_features

SEEDS = BENCHMARK_SEEDS  # 러너 공용 (구 [42, 7, 123] — 분산 추정 표본 부족으로 10개로 확대)
TARGET_KMS = [3.0, 5.0]
START_NODES = [1, 41417, 111383, 175895, 179044]  # largest_cc(=전체 그래프)에서 seed=2026으로 무작위 추출
# grasp-circular(기존 비교 기준)는 2026-09-11 커밋 4c7c924에서 SOLVER_REGISTRY에서 빠져
# 제외했다. 비교 기준이 사라진 이 러너의 존치 여부는 순환 시나리오 재작성 때 정한다.
ALGOS = ["grasp-wp-local", "grasp-wp-vnd", "grasp-wp-vns"]
TIMEOUT_SEC = 400.0  # VNS가 target_km=5.0에서 최대 250초 안팎 걸리는 것을 감안한 여유

_POOL_GRAPH = None
# 주의(2026-08-30): 워커가 처리하는 모든 조합(seed×target_km×start_node×algo)이 이
# 전역을 그대로 재사용한다 — 그래프를 변형하는 engine을 추가한다면 자체 G.copy()가
# 있는지 반드시 확인할 것(규칙은 benchmarks/benchmark.py 모듈 docstring "그래프
# 공유·변형 규칙" 참고).


def _pool_worker_init():
    global _POOL_GRAPH
    _POOL_GRAPH = _load_default_graph()
    precompute_scoring_features(_POOL_GRAPH)


def _pool_worker_task(solver_key: str, start_node: int, target_km: float, seed: int) -> dict:
    """단일 (solver, start_node, target_km, seed) 조합 실행.

    결과 행 생성은 benchmarks/results.py::run_solver_task()가 전담한다 — 예전에는 이
    함수가 dict 리터럴을 직접 들고 있어서, 컬럼이 추가될 때마다 여기가 빠졌다
    (num_waypoints_used / effective_waypoints_used / pool_cache_* 4종이 실제로 누락).
    """
    params = {
        "target_km": target_km,
        "seed": seed,
        "time_budget_sec": DEFAULT_TIME_BUDGET_SEC,
    }
    return run_solver_task(SOLVER_REGISTRY[solver_key], _POOL_GRAPH, start_node, start_node, params)


def main():
    conditions = [
        (algo, start_node, target_km, seed)
        for seed in SEEDS
        for target_km in TARGET_KMS
        for start_node in START_NODES
        for algo in ALGOS
    ]
    print(
        f"조건 {len(SEEDS)}seed × {len(TARGET_KMS)}target_km × {len(START_NODES)}start_node "
        f"× {len(ALGOS)}algo = {len(conditions)}개 실행", flush=True,
    )

    print("워커 풀 준비 중...", flush=True)
    t0 = time.perf_counter()
    pool = multiprocessing.get_context("spawn").Pool(processes=6, initializer=_pool_worker_init)
    print(f"워커 풀 준비 완료: {time.perf_counter() - t0:.1f}초", flush=True)

    t_start = time.perf_counter()
    async_results = [
        (algo, start_node, target_km, seed, pool.apply_async(_pool_worker_task, args=(algo, start_node, target_km, seed)))
        for algo, start_node, target_km, seed in conditions
    ]

    rows = []
    for i, (algo, start_node, target_km, seed, ar) in enumerate(async_results, 1):
        solver = SOLVER_REGISTRY[algo]
        try:
            row = ar.get(timeout=TIMEOUT_SEC)
        except multiprocessing.TimeoutError:
            row = failed_row(solver, "timeout", TIMEOUT_SEC, f"timeout after {TIMEOUT_SEC}s", target_km)
        row["seed"] = seed
        row["start_node"] = start_node
        rows.append(row)
        elapsed_total = time.perf_counter() - t_start
        print(
            f"[{i}/{len(async_results)}] {algo} start={start_node} target_km={target_km} seed={seed} "
            f"-> status={row['status']} elapsed_sec={row['elapsed_sec']:.1f} (누적 {elapsed_total:.0f}s)",
            flush=True,
        )
        # 중간 저장 — 장시간 실행 도중 중단돼도 그때까지 결과는 보존한다.
        pd.DataFrame(rows, columns=["seed", "start_node", *RESULT_COLUMNS]).to_csv(
            "benchmarks/min_separation_validation_results.csv", index=False,
        )

    pool.close()
    pool.join()

    result_df = pd.DataFrame(rows, columns=["seed", "start_node", *RESULT_COLUMNS])
    out_path = "benchmarks/min_separation_validation_results.csv"
    result_df.to_csv(out_path, index=False)
    meta_path = save_run_metadata(
        out_path, runner="run_min_separation_validation",
        seeds=SEEDS, target_kms=TARGET_KMS, start_nodes=START_NODES, algos=ALGOS,
        workers=6, timeout_sec=TIMEOUT_SEC,
    )

    print(f"\n전체 소요 시간: {time.perf_counter() - t_start:.1f}초")
    print(f"결과 저장 완료: {out_path}")
    print(f"메타데이터 저장 완료: {meta_path}\n")

    print("=== 알고리즘별 요약 ===")
    summary = result_df.groupby("algorithm").agg(
        시도횟수=("status", "count"),
        성공=("status", lambda s: (s == "ok").sum()),
        feasible비율=("feasible", lambda s: s.mean() if s.notna().any() else None),
        평균초=("elapsed_sec", "mean"),
        최대초=("elapsed_sec", "max"),
        평균거리편차km=("distance_deviation_km", "mean"),
        평균재통행=("repeated_edge_ratio", "mean"),  # 구 평균자기중복(edge_overlap_ratio)
        평균원형성=("circularity_q", "mean"),
        최소거리위반건수=("waypoint_separation_m", lambda s: None),  # 아래에서 별도 계산
    ).round(4)
    print(summary.to_string())

    # P2-P3 최소거리 위반 건수(요청서 §7.2 성공판정 3번: 위반 0건이어야 함)
    grasp_wp_rows = result_df[result_df["algorithm"].str.startswith("GRASP-Waypoint", na=False)]
    violations = grasp_wp_rows[
        grasp_wp_rows["waypoint_separation_m"].notna()
        & grasp_wp_rows["min_waypoint_separation_m"].notna()
        & (grasp_wp_rows["waypoint_separation_m"] < grasp_wp_rows["min_waypoint_separation_m"])
    ]
    print(f"\nP2-P3 최소거리 위반 건수: {len(violations)}건 (grasp-wp-* 중 feasible/fallback으로 실제 경로가 나온 행 기준)")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] [%(name)s] %(message)s")
    main()
