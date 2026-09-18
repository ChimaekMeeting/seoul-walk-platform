"""
benchmarks/run_grasp_alns_param_tuning.py

grasp-wp-alns의 남은 구축 파라미터(distance_tolerance_ratio, angle_diversity_weight_m,
grasp_iters)를 개별 통계 검증한다 (이슈 #427 후속 — 가벼운 스크리닝에서 셋 다 단일
샘플 신호가 나와 rcl_size와 동일한 방식으로 검증). min_waypoint_separation_ratio는
grasp-wp-alns와 beam-wp-vns가 정반대 방향 신호를 보여 해석이 애매해 이번 라운드에서
제외했다.

grasp-wp-alns만 대상이다 — 스크리닝에서 beam-wp-vns는 재통행률이 이미 0이라 신호가
없었다. 당시 확정값(alns_iterations=10, rcl_size=16)은 고정한 채 대상 파라미터만 바꿨다.
확정값은 지금 엔진 알고리즘별 기본값(circular_grasp_waypoint_alns.py)이라 params에 따로
싣지 않는다. 그 뒤 확정된 값(angle_diversity_weight_m=0.0, alns_candidate_limit=2)도 함께
적용되므로 다시 돌리면 기존 결과 CSV와 수치가 다를 수 있다.

target_km=7만 사용(원안 그리드와 동일 축소 이유). 튜닝 집합 4개 지점 x 시드 10개.

실행:
    python -m benchmarks.run_grasp_alns_param_tuning --param distance_tolerance_ratio
    python -m benchmarks.run_grasp_alns_param_tuning --param angle_diversity_weight_m
    python -m benchmarks.run_grasp_alns_param_tuning --param grasp_iters
    python -m benchmarks.run_grasp_alns_param_tuning --param grasp_iters --dry-run
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
ALGO = "grasp-wp-alns"

TUNING_STARTS = {
    "hongdae": ("dense", 37.557192, 126.925381),
    "gyeongbok": ("medium", 37.575771, 126.973297),
    "namsan": ("sparse", 37.551169, 126.988227),
    "bukhan": ("rural", 37.663000, 127.011000),
}

# 후보값 = 극단값 스크리닝에서 쓴 두 값 + 현재 기본값
PARAM_CANDIDATES = {
    "distance_tolerance_ratio": [0.02, 0.05, 0.15],
    "angle_diversity_weight_m": [0.0, 1500.0, 3000.0],
    "grasp_iters": [8, 24, 48],
}

TIMEOUT_SEC = 600.0
CHECKPOINT_EVERY = 25

_POOL_GRAPH = None


def _pool_worker_init():
    global _POOL_GRAPH
    _POOL_GRAPH = _load_default_graph()
    precompute_scoring_features(_POOL_GRAPH)


def _pool_worker_task(param: str, value, start_node, seed: int) -> dict:
    params = {
        "target_km": TARGET_KM, "num_waypoints": NUM_WAYPOINTS,
        "time_budget_sec": DEFAULT_TIME_BUDGET_SEC, "seed": seed,
        param: value,
    }
    return run_solver_task(SOLVER_REGISTRY[ALGO], _POOL_GRAPH, start_node, start_node, params)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--param", choices=list(PARAM_CANDIDATES), required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    values = PARAM_CANDIDATES[args.param]
    total = len(TUNING_STARTS) * len(values) * len(BENCHMARK_SEEDS)
    print(f"{ALGO} / {args.param} {values}: 출발지 {len(TUNING_STARTS)} x 값 {len(values)} x "
          f"시드 {len(BENCHMARK_SEEDS)} = 총 {total}회 (target_km={TARGET_KM})", flush=True)
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
        {"start_id": start_id, "tier": tier, "start_node": start_node, "value": value, "seed": seed}
        for start_id, (tier, start_node) in resolved.items()
        for value in values
        for seed in BENCHMARK_SEEDS
    ]

    t_start = time.perf_counter()
    async_results = [
        (cond, pool.apply_async(_pool_worker_task, args=(args.param, cond["value"], cond["start_node"], cond["seed"])))
        for cond in conditions
    ]

    out_path = f"benchmarks/grasp_alns_{args.param}_tuning_7km_results.csv"
    columns = ["start_id", "tier", "param", "value", "target_km", "num_waypoints", "seed", *RESULT_COLUMNS]

    rows = []
    for i, (cond, ar) in enumerate(async_results, 1):
        solver = SOLVER_REGISTRY[ALGO]
        try:
            row = ar.get(timeout=TIMEOUT_SEC)
        except multiprocessing.TimeoutError:
            row = failed_row(solver, "timeout", TIMEOUT_SEC, f"timeout after {TIMEOUT_SEC}s",
                              TARGET_KM, circular=True)
        row["start_id"] = cond["start_id"]
        row["tier"] = cond["tier"]
        row["param"] = args.param
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
        out_path, runner=f"run_grasp_alns_param_tuning(param={args.param})",
        algo=ALGO, param=args.param, values=values, target_km=TARGET_KM,
        num_waypoints=NUM_WAYPOINTS, tuning_starts=TUNING_STARTS, seeds=BENCHMARK_SEEDS,
        workers=args.workers, timeout_sec=TIMEOUT_SEC, time_budget_sec=DEFAULT_TIME_BUDGET_SEC,
    )

    print(f"\n전체 소요 시간: {time.perf_counter() - t_start:.1f}초")
    print(f"결과 저장 완료: {out_path}")
    print(f"메타데이터 저장 완료: {meta_path}\n")

    print(f"=== {args.param}별 요약 ===")
    summary = result_df.groupby("value").agg(
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
