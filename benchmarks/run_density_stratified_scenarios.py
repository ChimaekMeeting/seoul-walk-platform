"""
benchmarks/run_density_stratified_scenarios.py

밀도 층화 순환 경로 시나리오 러너 (2026-09-12, 이슈: 순환 경로 벤치마크 시나리오 확장).

기존 run_all_scenarios.py는 datasets/route_engine.json의 flat scenario 목록만 읽고
params에 num_waypoints를 넣지 않아(run_all_scenarios.py:151-155) 전 시나리오가 엔진
기본값 N=2로 고정돼 있었다. 이 러너는 별도 데이터셋
(datasets/circular_density_stratified.json)의 start_points x target_kms x
num_waypoints 곱집합을 돈다 — route_engine.json과 그 소비자(run_all_scenarios.py)는
건드리지 않는다.

두 단계로 나눠 돈다(--stage로 선택):
    1단계(탐색): 전 알고리즘 시드 1회(BENCHMARK_SEEDS[0]). 실행 가능 영역 지도, 게이트
                  임계값 분포, 퇴화 사례 수집이 목적. 여기서 이상 없음을 확인한 뒤
                  2단계로 넘어간다.
    2단계(본실행): SEED_SENSITIVE_SOLVERS는 BENCHMARK_SEEDS 10개 전부, 그 외(beam-wp)는
                  1회만(run_all_scenarios.py::_scenario_tasks와 동일 규칙).
                  장시간 실행이므로 CHECKPOINT_EVERY마다 중간 저장한다
                  (run_alns_sweep.py:39 패턴).

좌표만 두고 node_id를 저장하지 않는 이유: fixture를 다시 빌드하면 노드 ID는 달라지지만
좌표는 그대로이므로, PathUtils.find_nearest_node()로 실행 시점에 해석하는 편이
재현성이 높다.

실행:
    python -m benchmarks.run_density_stratified_scenarios --stage 1
    python -m benchmarks.run_density_stratified_scenarios --stage 2
    python -m benchmarks.run_density_stratified_scenarios --stage 2 --dry-run   # 실행 수만 계산
"""

import argparse
import itertools
import json
import multiprocessing
import time

import pandas as pd

from benchmarks.benchmark import _load_default_graph, SEED_SENSITIVE_SOLVERS, SOLVER_REGISTRY
from benchmarks.config import (
    BENCHMARK_SEEDS, CIRCULAR_BENCHMARK_PROFILE, DATASETS_DIR, DEFAULT_TIME_BUDGET_SEC,
)
from benchmarks.results import RESULT_COLUMNS, failed_row, run_solver_task
from benchmarks.run_metadata import save_run_metadata
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.scoring.scoring_engine import precompute_scoring_features

DATASET_PATH = DATASETS_DIR / "circular_density_stratified.json"

# beam/grasp-waypoint 9종 — run_all_scenarios.py::CIRCULAR_ALGOS와 동일 목록. 이 러너
# 전용으로 다시 정의한 이유는 신규 필드(num_waypoints)를 추가하는 실행 경로를
# route_engine.json 소비자와 완전히 분리해 두기 위해서다.
ALGOS = [
    "grasp-wp-local", "grasp-wp-vnd", "grasp-wp-vns", "grasp-wp-alns",
    "beam-wp", "beam-wp-local", "beam-wp-vnd", "beam-wp-vns", "beam-wp-alns",
]

TIMEOUT_SEC = 600.0  # 400 -> 600 (9km grasp-wp-vns 단독 170.8초 실측 + 6워커 경합 여유)
CHECKPOINT_EVERY = 25

_POOL_GRAPH = None
# 주의: 워커가 처리하는 모든 태스크가 이 전역을 재사용한다 — 그래프를 변형하는 engine을
# 추가한다면 자체 G.copy()가 있는지 반드시 확인할 것(규칙은 benchmark.py 모듈 docstring
# "그래프 공유·변형 규칙" 참고).


def _pool_worker_init():
    global _POOL_GRAPH
    _POOL_GRAPH = _load_default_graph()
    precompute_scoring_features(_POOL_GRAPH)


def _pool_worker_task(solver_key: str, start_node, target_km: float, num_waypoints: int, seed) -> dict:
    params = {
        "target_km": target_km,
        "profile": CIRCULAR_BENCHMARK_PROFILE,
        "time_budget_sec": DEFAULT_TIME_BUDGET_SEC,
        "num_waypoints": num_waypoints,
    }
    if seed is not None:
        params["seed"] = seed
    return run_solver_task(SOLVER_REGISTRY[solver_key], _POOL_GRAPH, start_node, start_node, params)


def _seed_plan(stage: str) -> list[tuple[str, int | None]]:
    """stage 1: 전 알고리즘 시드 1회(BENCHMARK_SEEDS[0]) — 우연이 아니라 커버리지가 목적.
    stage 2: SEED_SENSITIVE_SOLVERS는 BENCHMARK_SEEDS 전부, 그 외는 1회만
    (run_all_scenarios.py::_scenario_tasks와 동일 규칙 — beam-wp는 시드를 읽지 않는다)."""
    if stage == "1":
        return [(algo, BENCHMARK_SEEDS[0]) for algo in ALGOS]
    tasks: list[tuple[str, int | None]] = []
    for algo in ALGOS:
        if algo in SEED_SENSITIVE_SOLVERS:
            tasks.extend((algo, seed) for seed in BENCHMARK_SEEDS)
        else:
            tasks.append((algo, None))
    return tasks


def _load_dataset() -> dict:
    with open(DATASET_PATH, encoding="utf-8") as f:
        return json.load(f)


def _resolve_conditions(dataset: dict, graph) -> list[dict]:
    """start_points x target_kms x num_waypoints 곱집합을 노드로 해석해서 편다."""
    utils = PathUtils(graph)
    resolved_starts = [
        {**sp, "node": utils.find_nearest_node(sp["lat"], sp["lon"])}
        for sp in dataset["start_points"]
    ]
    return [
        {
            "start_id": sp["id"], "start_label": sp["label"], "tier": sp["tier"],
            "start_node": sp["node"], "target_km": target_km, "num_waypoints": n,
        }
        for sp, target_km, n in itertools.product(
            resolved_starts, dataset["target_kms"], dataset["num_waypoints"],
        )
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", choices=["1", "2"], required=True,
                         help="1=탐색(시드 1회), 2=본실행(SEED_SENSITIVE_SOLVERS는 시드 10회)")
    parser.add_argument("--dry-run", action="store_true",
                         help="실행하지 않고 총 실행 수만 계산해서 출력")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    dataset = _load_dataset()
    seed_plan = _seed_plan(args.stage)
    n_scenario_combos = (
        len(dataset["start_points"]) * len(dataset["target_kms"]) * len(dataset["num_waypoints"])
    )
    total = n_scenario_combos * len(seed_plan)
    print(
        f"stage={args.stage}: 출발지 {len(dataset['start_points'])} x 거리 {len(dataset['target_kms'])} x "
        f"N {dataset['num_waypoints']} x (algo, seed) 조합 {len(seed_plan)} = 총 {total}회",
        flush=True,
    )
    if args.dry_run:
        return

    graph = _load_default_graph()  # 부모 프로세스: find_nearest_node 해석에만 사용
    conditions = _resolve_conditions(dataset, graph)

    print("워커 풀 준비 중...", flush=True)
    t0 = time.perf_counter()
    pool = multiprocessing.get_context("spawn").Pool(processes=args.workers, initializer=_pool_worker_init)
    print(f"워커 풀 준비 완료: {time.perf_counter() - t0:.1f}초", flush=True)

    t_start = time.perf_counter()
    async_results = [
        (cond, algo, seed, pool.apply_async(
            _pool_worker_task,
            args=(algo, cond["start_node"], cond["target_km"], cond["num_waypoints"], seed),
        ))
        for cond in conditions
        for algo, seed in seed_plan
    ]

    out_path = f"benchmarks/density_stratified_stage{args.stage}_results.csv"
    columns = ["start_id", "start_label", "tier", "target_km", "num_waypoints", "seed", *RESULT_COLUMNS]

    rows = []
    for i, (cond, algo, seed, ar) in enumerate(async_results, 1):
        solver = SOLVER_REGISTRY[algo]
        try:
            row = ar.get(timeout=TIMEOUT_SEC)
        except multiprocessing.TimeoutError:
            row = failed_row(solver, "timeout", TIMEOUT_SEC, f"timeout after {TIMEOUT_SEC}s",
                              cond["target_km"], circular=True)
        row["start_id"] = cond["start_id"]
        row["start_label"] = cond["start_label"]
        row["tier"] = cond["tier"]
        row["target_km"] = cond["target_km"]
        row["num_waypoints"] = cond["num_waypoints"]
        row["seed"] = seed
        rows.append(row)

        if i % CHECKPOINT_EVERY == 0 or i == len(async_results):
            print(f"[{i}/{len(async_results)}] 누적 {time.perf_counter() - t_start:.0f}s", flush=True)
            pd.DataFrame(rows, columns=columns).to_csv(out_path, index=False)

    pool.close()
    pool.join()

    result_df = pd.DataFrame(rows, columns=columns)
    meta_path = save_run_metadata(
        out_path, runner=f"run_density_stratified_scenarios(stage={args.stage})",
        stage=args.stage, dataset=str(DATASET_PATH),
        start_points=dataset["start_points"], target_kms=dataset["target_kms"],
        num_waypoints=dataset["num_waypoints"], algos=ALGOS,
        seeds=BENCHMARK_SEEDS if args.stage == "2" else [BENCHMARK_SEEDS[0]],
        workers=args.workers, timeout_sec=TIMEOUT_SEC, time_budget_sec=DEFAULT_TIME_BUDGET_SEC,
        circular_profile=CIRCULAR_BENCHMARK_PROFILE,
    )

    print(f"\n전체 소요 시간: {time.perf_counter() - t_start:.1f}초")
    print(f"결과 저장 완료: {out_path}")
    print(f"메타데이터 저장 완료: {meta_path}\n")

    print("=== tier x num_waypoints 게이트 통과율 ===")
    summary = result_df.groupby(["tier", "num_waypoints"]).agg(
        시도횟수=("status", "count"),
        성공=("status", lambda s: (s == "ok").sum()),
        게이트통과율=("passed", lambda s: s.mean() if s.notna().any() else None),
        평균초=("elapsed_sec", "mean"),
        최대초=("elapsed_sec", "max"),
    ).round(4)
    print(summary.to_string())
    print(
        "\n[주의] 위 평균은 성공한 행만으로 계산됩니다. 조건별 짝지은 비교와 분산·최악값은 "
        "별도 집계(aggregate_results.py)에서 num_waypoints를 그룹핑 키로 추가해 내야 합니다."
    )


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] [%(name)s] %(message)s")
    main()
