"""
benchmarks/run_grasp_alns_iterations_9km_check.py

grasp-wp-alns.alns_iterations=10 튜닝 결론(run_refinement_tuning_sweep.py 청크 A)을
target_km=9에서 재검증한다 (이슈 #427 To-Do).

청크 A의 튜닝 집합은 target_km {3,7}만 포함했다. 그런데 9km 단일 샘플 확인(bukhan,
N=4, seed=42)에서는 iterations=10이 30보다 뚜렷이 나빴다(cost=6865.3/재통행=0.279 대
cost=8663.1/재통행=0.006) — is_optimal() 조기종료가 9km처럼 어려운 조건에서는 30회
전에 트리거되지 않아, 10회로는 반복 상한에 걸려 나쁜 해로 끝난 것으로 보인다. {3,7}km
에서는 20/30과 통계적으로 동일했던 결론(p>=0.73)이 9km에서도 유지되는지 같은 방식
(2-비율 z검정, Mann-Whitney U)으로 확인한다.

튜닝 집합과 동일한 4개 지점(홍대/경복궁/남산/북한산) x num_waypoints=4 고정,
target_km=9만 x alns_iterations {10,20,30} x 시드 10개.

실행:
    python -m benchmarks.run_grasp_alns_iterations_9km_check
    python -m benchmarks.run_grasp_alns_iterations_9km_check --dry-run
"""

import argparse
import multiprocessing
import time

import pandas as pd

from benchmarks.benchmark import _load_default_graph, SOLVER_REGISTRY
from benchmarks.config import BENCHMARK_SEEDS, DEFAULT_TIME_BUDGET_SEC
from benchmarks.results import RESULT_COLUMNS, failed_row, run_solver_task
from benchmarks.run_metadata import save_run_metadata
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.scoring.scoring_engine import precompute_scoring_features
from src.route_engine.weighted_cost_runtime import attach_weighted_cost, prepare_weighted_cost

NUM_WAYPOINTS = 4
TARGET_KM = 9.0
ITERATIONS_VALUES = (10, 20, 30)

TUNING_STARTS = {
    "hongdae": ("dense", 37.557192, 126.925381),
    "gyeongbok": ("medium", 37.575771, 126.973297),
    "namsan": ("sparse", 37.551169, 126.988227),
    "bukhan": ("rural", 37.663000, 127.011000),
}

TIMEOUT_SEC = 600.0
CHECKPOINT_EVERY = 25

_POOL_GRAPH = None


def _pool_worker_init():
    global _POOL_GRAPH
    _POOL_GRAPH = _load_default_graph()
    precompute_scoring_features(_POOL_GRAPH)
    # 프로덕션 dependencies.py::init_route_service()와 동일한 1회성 준비(#462) —
    # 워커가 곧바로 cost_context(WeightedEdgeCost)를 만들 수 있도록 적재율을 붙여 둔다.
    attach_weighted_cost(_POOL_GRAPH, prepare_weighted_cost(
        _POOL_GRAPH, enabled=True, coverage_min_ratio=0.95,
    ))


def _pool_worker_task(start_node, iterations: int, seed: int) -> dict:
    params = {
        "target_km": TARGET_KM,
        "num_waypoints": NUM_WAYPOINTS,
        "time_budget_sec": DEFAULT_TIME_BUDGET_SEC,
        "alns_iterations": iterations,
        "seed": seed,
    }
    return run_solver_task(SOLVER_REGISTRY["grasp-wp-alns"], _POOL_GRAPH, start_node, start_node, params)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    total = len(TUNING_STARTS) * len(ITERATIONS_VALUES) * len(BENCHMARK_SEEDS)
    print(f"출발지 {len(TUNING_STARTS)} x iterations {ITERATIONS_VALUES} x 시드 {len(BENCHMARK_SEEDS)} "
          f"= 총 {total}회 (target_km={TARGET_KM})", flush=True)
    if args.dry_run:
        return

    graph = _load_default_graph()
    utils = PathUtils(graph)
    resolved = {
        start_id: (tier, utils.find_nearest_node(lat, lon))
        for start_id, (tier, lat, lon) in TUNING_STARTS.items()
    }

    print("워커 풀 준비 중...", flush=True)
    t0 = time.perf_counter()
    pool = multiprocessing.get_context("spawn").Pool(processes=args.workers, initializer=_pool_worker_init)
    print(f"워커 풀 준비 완료: {time.perf_counter() - t0:.1f}초", flush=True)

    conditions = [
        {"start_id": start_id, "tier": tier, "start_node": start_node, "iterations": it, "seed": seed}
        for start_id, (tier, start_node) in resolved.items()
        for it in ITERATIONS_VALUES
        for seed in BENCHMARK_SEEDS
    ]

    t_start = time.perf_counter()
    async_results = [
        (cond, pool.apply_async(_pool_worker_task, args=(cond["start_node"], cond["iterations"], cond["seed"])))
        for cond in conditions
    ]

    out_path = "benchmarks/grasp_alns_iterations_9km_results.csv"
    columns = ["start_id", "tier", "target_km", "num_waypoints", "iterations", "seed", *RESULT_COLUMNS]

    rows = []
    for i, (cond, ar) in enumerate(async_results, 1):
        solver = SOLVER_REGISTRY["grasp-wp-alns"]
        try:
            row = ar.get(timeout=TIMEOUT_SEC)
        except multiprocessing.TimeoutError:
            row = failed_row(solver, "timeout", TIMEOUT_SEC, f"timeout after {TIMEOUT_SEC}s",
                              TARGET_KM, circular=True)
        row["start_id"] = cond["start_id"]
        row["tier"] = cond["tier"]
        row["target_km"] = TARGET_KM
        row["num_waypoints"] = NUM_WAYPOINTS
        row["iterations"] = cond["iterations"]
        row["seed"] = cond["seed"]
        rows.append(row)

        if i % CHECKPOINT_EVERY == 0 or i == len(async_results):
            print(f"[{i}/{len(async_results)}] 누적 {time.perf_counter() - t_start:.0f}s", flush=True)
            pd.DataFrame(rows, columns=columns).to_csv(out_path, index=False)

    pool.close()
    pool.join()

    result_df = pd.DataFrame(rows, columns=columns)
    meta_path = save_run_metadata(
        out_path, runner="run_grasp_alns_iterations_9km_check",
        target_km=TARGET_KM, num_waypoints=NUM_WAYPOINTS, iterations_values=ITERATIONS_VALUES,
        tuning_starts=TUNING_STARTS, seeds=BENCHMARK_SEEDS,
        workers=args.workers, timeout_sec=TIMEOUT_SEC, time_budget_sec=DEFAULT_TIME_BUDGET_SEC,
    )

    print(f"\n전체 소요 시간: {time.perf_counter() - t_start:.1f}초")
    print(f"결과 저장 완료: {out_path}")
    print(f"메타데이터 저장 완료: {meta_path}\n")

    print("=== iterations별 요약 ===")
    summary = result_df.groupby("iterations").agg(
        시도횟수=("status", "count"),
        성공=("status", lambda s: (s == "ok").sum()),
        게이트통과율=("passed", lambda s: s.mean() if s.notna().any() else None),
        평균초=("elapsed_sec", "mean"),
        최대초=("elapsed_sec", "max"),
        평균거리편차km=("distance_deviation_km", "mean"),
    ).round(4)
    print(summary.to_string())


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] [%(name)s] %(message)s")
    main()
