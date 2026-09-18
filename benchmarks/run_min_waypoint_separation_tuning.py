"""
benchmarks/run_min_waypoint_separation_tuning.py

min_waypoint_separation_ratio 통계 검증 (이슈 #427 후속). 가벼운 스크리닝에서
grasp-wp-alns(0.05->0.0, 0.4->0.144 악화)와 beam-wp-vns(0.05->0.092, 0.4->0.0
개선)가 정반대 방향 신호를 보여, 다른 3개 파라미터와 달리 GRASP·Beam 양쪽 다
검증해야 방향을 규명할 수 있다.

당시 확정값은 고정한 채 이 파라미터만 바꿨다. 확정값은 지금 엔진 알고리즘별 기본값
(circular_grasp_waypoint_alns.py, circular_beam_waypoint_vns.py)이라 params에 따로 싣지
않는다. 그 뒤 확정된 값(alns_candidate_limit=2)도 함께 적용되므로 다시 돌리면 기존 결과
CSV와 수치가 다를 수 있다. target_km=7만 사용, 튜닝 집합 4개 지점 x 시드 10개.

실행:
    python -m benchmarks.run_min_waypoint_separation_tuning
    python -m benchmarks.run_min_waypoint_separation_tuning --dry-run
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

TARGET_KM = 7.0
NUM_WAYPOINTS = 4
ALGOS = ["grasp-wp-alns", "beam-wp-vns"]
VALUES = [0.05, 0.20, 0.40]  # 0.20 = 엔진 기본값

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


def _pool_worker_task(algo: str, value: float, start_node, seed: int) -> dict:
    params = {
        "target_km": TARGET_KM, "num_waypoints": NUM_WAYPOINTS,
        "time_budget_sec": DEFAULT_TIME_BUDGET_SEC, "seed": seed,
        "min_waypoint_separation_ratio": value,
    }
    return run_solver_task(SOLVER_REGISTRY[algo], _POOL_GRAPH, start_node, start_node, params)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    total = len(TUNING_STARTS) * len(ALGOS) * len(VALUES) * len(BENCHMARK_SEEDS)
    print(f"출발지 {len(TUNING_STARTS)} x 알고리즘 {ALGOS} x 값 {VALUES} x 시드 "
          f"{len(BENCHMARK_SEEDS)} = 총 {total}회 (target_km={TARGET_KM})", flush=True)
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
        {"start_id": start_id, "tier": tier, "start_node": start_node, "algo": algo, "value": value, "seed": seed}
        for start_id, (tier, start_node) in resolved.items()
        for algo in ALGOS
        for value in VALUES
        for seed in BENCHMARK_SEEDS
    ]

    t_start = time.perf_counter()
    async_results = [
        (cond, pool.apply_async(_pool_worker_task, args=(cond["algo"], cond["value"], cond["start_node"], cond["seed"])))
        for cond in conditions
    ]

    out_path = "benchmarks/min_waypoint_separation_tuning_7km_results.csv"
    columns = ["start_id", "tier", "algo_key", "value", "target_km", "num_waypoints", "seed", *RESULT_COLUMNS]

    rows = []
    for i, (cond, ar) in enumerate(async_results, 1):
        solver = SOLVER_REGISTRY[cond["algo"]]
        try:
            row = ar.get(timeout=TIMEOUT_SEC)
        except multiprocessing.TimeoutError:
            row = failed_row(solver, "timeout", TIMEOUT_SEC, f"timeout after {TIMEOUT_SEC}s",
                              TARGET_KM, circular=True)
        row["start_id"] = cond["start_id"]
        row["tier"] = cond["tier"]
        row["algo_key"] = cond["algo"]
        row["value"] = cond["value"]
        row["target_km"] = TARGET_KM
        row["num_waypoints"] = NUM_WAYPOINTS
        row["seed"] = cond["seed"]
        rows.append(row)

        if i % CHECKPOINT_EVERY == 0 or i == len(async_results):
            print(f"[{i}/{len(async_results)}] 누적 {time.perf_counter() - t_start:.0f}s", flush=True)
            pd.DataFrame(rows, columns=columns).to_csv(out_path, index=False)

    pool.close()
    pool.join()

    result_df = pd.DataFrame(rows, columns=columns)
    meta_path = save_run_metadata(
        out_path, runner="run_min_waypoint_separation_tuning",
        algos=ALGOS, values=VALUES, target_km=TARGET_KM, num_waypoints=NUM_WAYPOINTS,
        tuning_starts=TUNING_STARTS, seeds=BENCHMARK_SEEDS,
        workers=args.workers, timeout_sec=TIMEOUT_SEC, time_budget_sec=DEFAULT_TIME_BUDGET_SEC,
    )

    print(f"\n전체 소요 시간: {time.perf_counter() - t_start:.1f}초")
    print(f"결과 저장 완료: {out_path}")
    print(f"메타데이터 저장 완료: {meta_path}\n")

    print("=== algo_key x value 요약 ===")
    summary = result_df.groupby(["algo_key", "value"]).agg(
        시도횟수=("status", "count"),
        게이트통과율=("passed", lambda s: s.mean() if s.notna().any() else None),
        평균초=("elapsed_sec", "mean"),
        평균거리편차km=("distance_deviation_km", "mean"),
        평균재통행=("repeated_edge_ratio", "mean"),
    ).round(4)
    print(summary.to_string())


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] [%(name)s] %(message)s")
    main()
