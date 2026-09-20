"""편도 우회 밀도 층화 벤치마크.

1단계는 모든 조건을 대표 시드 하나로 빠르게 점검하고, 2단계는 동일 조건을
``BENCHMARK_SEEDS`` 10개로 고정 반복한다. 조건은 출발지 밀도, 출발-도착 물리 최단거리,
목표 우회 배율, 경유지 수, 거리/안전/편안/혼합 가중치다. 목표 거리는 artifact에서 계산한
물리 최단거리의 배수여서 불가능한 목표를 데이터셋에 고정하지 않는다.
"""

import argparse
import json
import multiprocessing
import time
from pathlib import Path

import networkx as nx
import pandas as pd

from benchmarks import aggregate_results
from benchmarks.benchmark import _load_default_graph, SOLVER_REGISTRY
from benchmarks.config import BENCHMARK_SEEDS, DATASETS_DIR, DEFAULT_TIME_BUDGET_SEC
from benchmarks.results import RESULT_COLUMNS, failed_row, run_solver_task
from benchmarks.run_metadata import save_run_metadata
from src.config.settings import settings
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.scoring.scoring_engine import precompute_scoring_features
from src.route_engine.weighted_cost_runtime import (
    attach_weighted_cost,
    build_request_cost_context,
    prepare_weighted_cost,
)

DATASET_PATH = DATASETS_DIR / "oneway_density_stratified.json"
ALGORITHM = "oneway-grasp-wp-alns"
TIMEOUT_SEC = 120.0
CHECKPOINT_EVERY = 20
_POOL_GRAPH = None


def _load_dataset() -> dict:
    with open(DATASET_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def _resolve_conditions(dataset: dict, graph) -> list[dict]:
    """현재 graph에서 시작·도착 노드와 물리 최단거리 기반 목표를 확정한다."""
    utils = PathUtils(graph)
    conditions = []
    for route in dataset["routes"]:
        start_node = utils.find_nearest_node(route["origin_lat"], route["origin_lon"])
        end_node = utils.find_nearest_node(route["destination_lat"], route["destination_lon"])
        if start_node is None or end_node is None:
            raise ValueError(f"노드 스냅 실패: {route['origin_id']} -> {route['destination_id']}")
        try:
            shortest_km = nx.shortest_path_length(graph, start_node, end_node, weight="length") / 1000
        except nx.NetworkXNoPath as exc:
            raise ValueError(f"물리 최단경로 없음: {route['origin_id']} -> {route['destination_id']}") from exc

        for multiplier in dataset["detour_multipliers"]:
            for num_waypoints in dataset["num_waypoints"]:
                for weight_mode, preferences in dataset["weight_conditions"].items():
                    conditions.append({
                        **route,
                        "start_node": start_node,
                        "end_node": end_node,
                        "shortest_distance_km": round(shortest_km, 4),
                        "detour_multiplier": multiplier,
                        "target_km": round(shortest_km * multiplier, 4),
                        "num_waypoints": num_waypoints,
                        "weight_mode": weight_mode,
                        "safety": preferences["safety"],
                        "comfort": preferences["comfort"],
                    })
    return conditions


def _stage_seeds(stage: str) -> list[int]:
    return [BENCHMARK_SEEDS[0]] if stage == "1" else list(BENCHMARK_SEEDS)


def _pool_worker_init():
    global _POOL_GRAPH
    _POOL_GRAPH = _load_default_graph()
    precompute_scoring_features(_POOL_GRAPH)
    attach_weighted_cost(_POOL_GRAPH, prepare_weighted_cost(
        _POOL_GRAPH, enabled=True, coverage_min_ratio=0.95,
    ))


def _task_params(condition: dict, seed: int) -> dict:
    context = build_request_cost_context(
        _POOL_GRAPH,
        safety_preference=condition["safety"],
        slope_preference=condition["comfort"],
        weight_limit=settings.WALK_WEIGHT_LIMIT,
        accident_ratio=settings.WALK_UNSAFE_ACCIDENT_RATIO,
    )
    return {
        "target_km": condition["target_km"],
        "num_waypoints": condition["num_waypoints"],
        "seed": seed,
        "time_budget_sec": DEFAULT_TIME_BUDGET_SEC,
        "weight_mode": condition["weight_mode"],
        "cost_context": context,
    }


def _pool_worker_task(condition: dict, seed: int) -> dict:
    return run_solver_task(
        SOLVER_REGISTRY[ALGORITHM], _POOL_GRAPH, condition["start_node"], condition["end_node"],
        _task_params(condition, seed),
    )


def _columns() -> list[str]:
    return [
        "mode", "origin_id", "origin_label", "origin_density_tier", "origin_density",
        "destination_id", "destination_label", "start_node", "end_node", "shortest_distance_km",
        "detour_multiplier", "weight_mode", "safety", "comfort", "num_waypoints", "seed",
        *RESULT_COLUMNS,
    ]


def _write_aggregates(rows: list[dict], out_path: Path) -> None:
    """2단계 결과에서 조건별 평균·표준편차·최악값·통과율을 즉시 별도 CSV로 낸다."""
    raw = pd.DataFrame(rows, columns=_columns())
    work = aggregate_results.add_derived_columns(raw)
    aggregate_results.per_condition(work).to_csv(
        out_path.with_name(f"{out_path.stem}_aggregate_by_condition.csv"), index=False,
    )
    aggregate_results.per_algorithm(work).to_csv(
        out_path.with_name(f"{out_path.stem}_aggregate_by_algorithm.csv"), index=False,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["1", "2"], required=True)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args(argv)

    out_path = args.out or Path(f"benchmarks/oneway_density_stage{args.stage}_results.csv")
    if out_path.exists() and not args.force:
        raise SystemExit(f"출력 파일이 이미 있습니다: {out_path} (--force로 덮어쓰기)")

    dataset = _load_dataset()
    graph = _load_default_graph()
    conditions = _resolve_conditions(dataset, graph)
    seeds = _stage_seeds(args.stage)
    total = len(conditions) * len(seeds)
    print(f"stage={args.stage}: 조건 {len(conditions)} x 고정 시드 {len(seeds)} = {total}회")
    if args.dry_run:
        return

    pool = multiprocessing.get_context("spawn").Pool(processes=args.workers, initializer=_pool_worker_init)
    started = time.perf_counter()
    async_results = [
        (condition, seed, pool.apply_async(_pool_worker_task, args=(condition, seed)))
        for condition in conditions for seed in seeds
    ]
    rows = []
    for index, (condition, seed, async_result) in enumerate(async_results, 1):
        try:
            row = async_result.get(timeout=TIMEOUT_SEC)
        except multiprocessing.TimeoutError:
            row = failed_row(
                SOLVER_REGISTRY[ALGORITHM], "timeout", TIMEOUT_SEC,
                f"timeout after {TIMEOUT_SEC}s", condition["target_km"], circular=False,
            )
        row.update({key: condition[key] for key in (
            "origin_id", "origin_label", "origin_density_tier", "origin_density",
            "destination_id", "destination_label", "start_node", "end_node", "shortest_distance_km",
            "detour_multiplier", "weight_mode", "safety", "comfort", "num_waypoints",
        )})
        row["mode"] = "oneway"
        row["seed"] = seed
        rows.append(row)
        if index % CHECKPOINT_EVERY == 0 or index == total:
            pd.DataFrame(rows, columns=_columns()).to_csv(out_path, index=False)
            print(f"[{index}/{total}] {time.perf_counter() - started:.0f}s", flush=True)

    pool.close()
    pool.join()
    _write_aggregates(rows, out_path)
    save_run_metadata(
        out_path, runner="run_oneway_density_stratified", stage=args.stage, dataset=str(DATASET_PATH),
        algorithm=ALGORITHM, seeds=seeds, workers=args.workers, timeout_sec=TIMEOUT_SEC,
        time_budget_sec=DEFAULT_TIME_BUDGET_SEC, weight_conditions=dataset["weight_conditions"],
    )
    print(f"완료: {out_path} (조건별/알고리즘별 집계 CSV도 함께 저장)")


if __name__ == "__main__":
    main()
