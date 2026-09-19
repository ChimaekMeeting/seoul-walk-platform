"""
benchmarks/run_grasp_alns_candidate_limit_check.py

grasp-wp-alns의 alns_candidate_limit이 품질과 무관한지 검증한다. 당시 엔진 기본 동작은
candidate_limit=cfg.rcl_size라(waypoint_refinement.py::_alns_config) 확정값
rcl_size=16이 구축 RCL과 ALNS 복구 후보 수를 함께 올렸다(이 검증 뒤 한도 2가 확정돼
GRASP_ALNS_OPTIONS에 들어갔다). 스크리닝(단일 샘플, 스크립트
미보존)은 "값에 무관하게 cost가 완전히 동일"이라고만 남겼는데, 이는 (1) ALNS가 구축
결과를 한 번도 개선하지 못했거나 (2) 옵션이 엔진에 닿지 않았거나(alns_search의
ValueError는 엔진이 조용히 건너뛴다) 둘 중 하나일 수 있어 ALNS 통계를 함께 남긴다.

나머지 확정값(alns_iterations=10, rcl_size=16, angle_diversity_weight_m=0.0)은 엔진
알고리즘별 기본값(circular_grasp_waypoint_alns.py)으로 고정되고 alns_candidate_limit만
params로 덮어쓴다. 후보값 2는 N=4에서 remove_count=ceil(4*0.3)=2라 허용되는
하한이다(waypoint_alns.py::_validate).

target_km=7, 튜닝 집합 4개 지점 x 시드 5개(BENCHMARK_SEEDS 앞 5개) x 값 3개 = 60회.

실행:
    poetry run python -m benchmarks.run_grasp_alns_candidate_limit_check
    poetry run python -m benchmarks.run_grasp_alns_candidate_limit_check --dry-run
"""

import argparse
import json
import multiprocessing
import time

import pandas as pd

from benchmarks.benchmark import _load_default_graph, SOLVER_REGISTRY
from benchmarks.config import BENCHMARK_SEEDS, DEFAULT_TIME_BUDGET_SEC
from benchmarks.results import RESULT_COLUMNS, failed_row, run_solver_task
from benchmarks.run_density_stratified_scenarios import algorithm_defaults
from benchmarks.run_grasp_alns_param_tuning import TUNING_STARTS
from benchmarks.run_metadata import save_run_metadata
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.scoring.scoring_engine import precompute_scoring_features
from src.route_engine.weighted_cost_runtime import attach_weighted_cost, prepare_weighted_cost

TARGET_KM = 7.0
NUM_WAYPOINTS = 4
ALGO = "grasp-wp-alns"
PARAM = "alns_candidate_limit"
VALUES = [2, 8, 16]
SEEDS = BENCHMARK_SEEDS[:5]

TIMEOUT_SEC = 600.0
CHECKPOINT_EVERY = 10
OUT_PATH = "benchmarks/grasp_alns_candidate_limit_check_7km_results.csv"

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


def _pool_worker_task(value: int, start_node, seed: int) -> dict:
    params = {
        "target_km": TARGET_KM, "num_waypoints": NUM_WAYPOINTS,
        "time_budget_sec": DEFAULT_TIME_BUDGET_SEC, "seed": seed,
        PARAM: value,
    }
    return run_solver_task(SOLVER_REGISTRY[ALGO], _POOL_GRAPH, start_node, start_node, params)


def _alns_fields(raw) -> dict:
    """alns_operator_stats JSON에서 "ALNS가 실제로 돌았는지·최종 해에 기여했는지"만 꺼낸다."""
    if not isinstance(raw, str) or not raw:
        return {"alns_calls": None, "alns_cost_calls": None, "alns_accepted_moves": None,
                "winner_alns_accepted": None}
    stats = json.loads(raw)
    winner = stats.get("winning_iteration") or {}
    return {
        "alns_calls": stats.get("alns_calls"),
        "alns_cost_calls": stats.get("total_cost_calls"),
        "alns_accepted_moves": stats.get("total_accepted_moves"),
        "winner_alns_accepted": winner.get("accepted"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    total = len(TUNING_STARTS) * len(VALUES) * len(SEEDS)
    print(f"{ALGO} / {PARAM} {VALUES}: 출발지 {len(TUNING_STARTS)} x 값 {len(VALUES)} x "
          f"시드 {len(SEEDS)} = 총 {total}회 (target_km={TARGET_KM}, 나머지는 {ALGO} 엔진 기본값)",
          flush=True)
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
        for value in VALUES
        for seed in SEEDS
    ]

    t_start = time.perf_counter()
    async_results = [
        (cond, pool.apply_async(_pool_worker_task, args=(cond["value"], cond["start_node"], cond["seed"])))
        for cond in conditions
    ]

    # target_km은 RESULT_COLUMNS에 이미 있어 앞에 다시 적지 않는다(헤더 중복 방지).
    columns = ["start_id", "tier", "param", "value", "num_waypoints", "seed",
               *RESULT_COLUMNS, "alns_calls", "alns_cost_calls", "alns_accepted_moves",
               "winner_alns_accepted"]

    rows = []
    for i, (cond, ar) in enumerate(async_results, 1):
        solver = SOLVER_REGISTRY[ALGO]
        try:
            row = ar.get(timeout=TIMEOUT_SEC)
        except multiprocessing.TimeoutError:
            row = failed_row(solver, "timeout", TIMEOUT_SEC, f"timeout after {TIMEOUT_SEC}s",
                              TARGET_KM, circular=True)
        row.update(_alns_fields(row.get("alns_operator_stats")))
        row["start_id"] = cond["start_id"]
        row["tier"] = cond["tier"]
        row["param"] = PARAM
        row["value"] = cond["value"]
        row["target_km"] = TARGET_KM
        row["num_waypoints"] = NUM_WAYPOINTS
        row["seed"] = cond["seed"]
        rows.append(row)

        if i % CHECKPOINT_EVERY == 0 or i == len(async_results):
            print(f"[{i}/{len(async_results)}] 누적 {time.perf_counter() - t_start:.0f}s", flush=True)
            pd.DataFrame(rows, columns=columns).to_csv(OUT_PATH, index=False)

    pool.close()
    pool.join()

    result_df = pd.DataFrame(rows, columns=columns)
    meta_path = save_run_metadata(
        OUT_PATH, runner="run_grasp_alns_candidate_limit_check",
        algo=ALGO, param=PARAM, values=VALUES, algorithm_defaults=algorithm_defaults([ALGO]),
        target_km=TARGET_KM, num_waypoints=NUM_WAYPOINTS, tuning_starts=TUNING_STARTS, seeds=SEEDS,
        workers=args.workers, timeout_sec=TIMEOUT_SEC, time_budget_sec=DEFAULT_TIME_BUDGET_SEC,
    )

    print(f"\n전체 소요 시간: {time.perf_counter() - t_start:.1f}초")
    print(f"결과 저장 완료: {OUT_PATH}")
    print(f"메타데이터 저장 완료: {meta_path}\n")

    print(f"=== {PARAM}별 요약 ===")
    summary = result_df.groupby("value").agg(
        시도횟수=("status", "count"),
        게이트통과율=("passed", lambda s: s.mean() if s.notna().any() else None),
        평균cost=("cost", "mean"),
        평균초=("elapsed_sec", "mean"),
        평균ALNS호출=("alns_calls", "mean"),
        평균ALNS비용호출=("alns_cost_calls", "mean"),
        ALNS채택률=("winner_alns_accepted", lambda s: s.dropna().astype(bool).mean() if s.notna().any() else None),
    ).round(4)
    print(summary.to_string())


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] [%(name)s] %(message)s")
    main()
