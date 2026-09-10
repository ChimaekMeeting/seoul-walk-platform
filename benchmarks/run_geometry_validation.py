"""
benchmarks/run_geometry_validation.py

원형성 진단 지표(d12/d23/d31/repeated_edge_ratio/waypoint_angle_diff_deg/
segment_balance_ratio/is_degenerate_loop, 2026-08-30 요청)가 추가된 이후의 다중 조건
재검증 러너. 이전 두 스크립트(run_min_separation_validation.py, run_alns_validation.py)의
CSV는 이 컬럼들이 생기기 전에 만들어져 집계에 쓸 수 없다 — 같은 seed×target_km×
start_node 격자에서 grasp-wp-local/vnd/vns/alns + grasp-circular(기존 비교 기준)를
한 번에 다시 실행해 새 컬럼이 포함된 CSV를 만든다.

실행:
    python -m benchmarks.run_geometry_validation
"""

import multiprocessing
import time

import pandas as pd

from benchmarks.benchmark import _load_default_graph, SOLVER_REGISTRY
from benchmarks.results import RESULT_COLUMNS, failed_row, run_solver_task
from src.route_engine.scoring.scoring_engine import precompute_scoring_features

SEEDS = [42, 7, 123]
TARGET_KMS = [3.0, 5.0]
START_NODES = [1, 41417, 111383, 175895, 179044]
ALGOS = ["grasp-wp-local", "grasp-wp-vnd", "grasp-wp-vns", "grasp-wp-alns", "grasp-circular"]
TIMEOUT_SEC = 400.0

_POOL_GRAPH = None
# 주의(2026-08-30): 워커가 처리하는 모든 조합이 이 전역을 그대로 재사용한다 — 그래프를
# 변형하는 engine을 추가한다면 자체 G.copy()가 있는지 반드시 확인할 것(규칙은
# benchmarks/benchmark.py 모듈 docstring "그래프 공유·변형 규칙" 참고).


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
    params = {"target_km": target_km, "seed": seed}
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
        pd.DataFrame(rows, columns=["seed", "start_node", *RESULT_COLUMNS]).to_csv(
            "benchmarks/geometry_validation_results.csv", index=False,
        )

    pool.close()
    pool.join()

    result_df = pd.DataFrame(rows, columns=["seed", "start_node", *RESULT_COLUMNS])
    out_path = "benchmarks/geometry_validation_results.csv"
    result_df.to_csv(out_path, index=False)

    print(f"\n전체 소요 시간: {time.perf_counter() - t_start:.1f}초")
    print(f"결과 저장 완료: {out_path}\n")

    print("=== 엔진별 원형성 집계 ===")
    summary = result_df.groupby("algorithm").agg(
        시도횟수=("status", "count"),
        성공=("status", lambda s: (s == "ok").sum()),
        degenerate_비율=("is_degenerate_loop", lambda s: s.mean() if s.notna().any() else None),
        중복률_평균=("repeated_edge_ratio", "mean"),
        중복률_최대=("repeated_edge_ratio", "max"),
        균형비_평균=("segment_balance_ratio", "mean"),
    ).round(4)
    print(summary.to_string())


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] [%(name)s] %(message)s")
    main()
