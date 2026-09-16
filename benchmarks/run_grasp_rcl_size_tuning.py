"""
benchmarks/run_grasp_rcl_size_tuning.py

GRASP 3종(Local/VND/ALNS)의 구축 파라미터 rcl_size 튜닝 (이슈 #427 To-Do 3).
Beam 계열의 beam_width에 대응하는 값 — _grasp_config_from_params()로 하네스에 새로
뚫은 노브를 처음 통계 검증한다.

7km만 사용한다(3km는 대체로 쉬운 조건이라 차이가 잘 안 드러나 원래 {3,7}km 그리드의
절반 비용으로 정보 손실을 최소화). 접전/애매한 결과가 나오면 3km나 시드를 추가해
재확인하고, 이미 결정된 값은 재검증하지 않는다.

후보값이 알고리즘마다 다른 이유: 9km 사전 검증에서 grasp-wp-vnd만 rcl_size=16에서
시간이 폭증했다(4 대비 9.6배, 394초). Local/ALNS는 16까지도 비용이 완만해(각 3.8배,
1.4배) 그대로 두고, VND만 12로 상한을 낮췄다.

튜닝 집합: 홍대(dense)/경복궁(medium)/남산(sparse)/북한산(rural) x num_waypoints=4
고정 x 시드 10개.

실행:
    python -m benchmarks.run_grasp_rcl_size_tuning
    python -m benchmarks.run_grasp_rcl_size_tuning --dry-run
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

TUNING_STARTS = {
    "hongdae": ("dense", 37.557192, 126.925381),
    "gyeongbok": ("medium", 37.575771, 126.973297),
    "namsan": ("sparse", 37.551169, 126.988227),
    "bukhan": ("rural", 37.663000, 127.011000),
}

CONFIGS = [
    ("grasp-wp-local", 4), ("grasp-wp-local", 8), ("grasp-wp-local", 16),
    ("grasp-wp-vnd", 4), ("grasp-wp-vnd", 8), ("grasp-wp-vnd", 12),
    ("grasp-wp-alns", 4), ("grasp-wp-alns", 8), ("grasp-wp-alns", 16),
]

TIMEOUT_SEC = 600.0
CHECKPOINT_EVERY = 25

_POOL_GRAPH = None


def _pool_worker_init():
    global _POOL_GRAPH
    _POOL_GRAPH = _load_default_graph()
    precompute_scoring_features(_POOL_GRAPH)


def _pool_worker_task(algo_key: str, start_node, rcl_size: int, seed: int) -> dict:
    params = {
        "target_km": TARGET_KM, "num_waypoints": NUM_WAYPOINTS,
        "time_budget_sec": DEFAULT_TIME_BUDGET_SEC,
        "rcl_size": rcl_size, "seed": seed,
    }
    return run_solver_task(SOLVER_REGISTRY[algo_key], _POOL_GRAPH, start_node, start_node, params)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    total = len(TUNING_STARTS) * len(CONFIGS) * len(BENCHMARK_SEEDS)
    print(f"출발지 {len(TUNING_STARTS)} x 설정 {len(CONFIGS)}개 x 시드 {len(BENCHMARK_SEEDS)} "
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
        {"start_id": start_id, "tier": tier, "start_node": start_node, "algo_key": algo_key,
         "rcl_size": rcl_size, "seed": seed}
        for start_id, (tier, start_node) in resolved.items()
        for algo_key, rcl_size in CONFIGS
        for seed in BENCHMARK_SEEDS
    ]

    t_start = time.perf_counter()
    async_results = [
        (cond, pool.apply_async(
            _pool_worker_task, args=(cond["algo_key"], cond["start_node"], cond["rcl_size"], cond["seed"]),
        ))
        for cond in conditions
    ]

    out_path = "benchmarks/grasp_rcl_size_tuning_7km_results.csv"
    columns = ["start_id", "tier", "algo_key", "rcl_size", "target_km", "num_waypoints", "seed", *RESULT_COLUMNS]

    rows = []
    for i, (cond, ar) in enumerate(async_results, 1):
        solver = SOLVER_REGISTRY[cond["algo_key"]]
        try:
            row = ar.get(timeout=TIMEOUT_SEC)
        except multiprocessing.TimeoutError:
            row = failed_row(solver, "timeout", TIMEOUT_SEC, f"timeout after {TIMEOUT_SEC}s",
                              TARGET_KM, circular=True)
        row["start_id"] = cond["start_id"]
        row["tier"] = cond["tier"]
        row["algo_key"] = cond["algo_key"]
        row["rcl_size"] = cond["rcl_size"]
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
        out_path, runner="run_grasp_rcl_size_tuning",
        target_km=TARGET_KM, num_waypoints=NUM_WAYPOINTS, configs=CONFIGS,
        tuning_starts=TUNING_STARTS, seeds=BENCHMARK_SEEDS,
        workers=args.workers, timeout_sec=TIMEOUT_SEC, time_budget_sec=DEFAULT_TIME_BUDGET_SEC,
    )

    print(f"\n전체 소요 시간: {time.perf_counter() - t_start:.1f}초")
    print(f"결과 저장 완료: {out_path}")
    print(f"메타데이터 저장 완료: {meta_path}\n")

    print("=== algo_key x rcl_size 요약 ===")
    summary = result_df.groupby(["algo_key", "rcl_size"]).agg(
        시도횟수=("status", "count"),
        게이트통과율=("passed", lambda s: s.mean() if s.notna().any() else None),
        평균초=("elapsed_sec", "mean"),
        최대초=("elapsed_sec", "max"),
        평균거리편차km=("distance_deviation_km", "mean"),
        평균재통행=("repeated_edge_ratio", "mean"),
    ).round(4)
    print(summary.to_string())


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] [%(name)s] %(message)s")
    main()
