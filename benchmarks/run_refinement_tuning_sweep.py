"""
benchmarks/run_refinement_tuning_sweep.py

정제 파라미터 튜닝 스윕 (2026-09-13, 대화 내 노브 유효성 사전 확인 결과 반영).

포함 노브(전부 극단값 비교로 유효성을 먼저 확인한 것만 사용):
    - beam_width: Beam 계열 전체(구축 단계)에서 유효 확인(4/8/16에서 astar_calls·cost가
      뚜렷이 다름).
    - alns_removal_fraction: Beam-Waypoint+ALNS에서만 유효. GRASP-Waypoint+ALNS는
      극단값(0.2 vs 0.6, 실제 제거 개수 1 vs 3)조차 결과가 완전히 같아 제외했다.
    - alns_iterations: GRASP-Waypoint+ALNS에서만 유효(10은 반복상한에 걸려 나쁜 해, 30부터
      수렴해 100과 동일 — 유효 구간이 10~30이라 후보를 {10,20,30}으로 좁혔다).
      Beam-Waypoint+ALNS는 어려운 조건(9km)에서도 10/30/100이 완전히 동일해 제외했다.
    - vns_max_shake_level: Beam-Waypoint+VNS에서 유효(2와 4가 cost·속도 모두 다름 — 3.5배
      속도차의 실제 트레이드오프). GRASP-Waypoint+VNS는 반복 무제한 문제로 이번 벤치마크
      전체에서 제외돼 있어(run_density_stratified_scenarios.py 참고) 대상에서 뺐다.

튜닝 집합: 밀도 층별 1개씩(hongdae=dense, gyeongbok=medium, namsan=sparse, bukhan=rural,
circular_density_stratified.json과 동일 좌표) x target_km={3,7} x num_waypoints=4 고정.
시드는 BENCHMARK_SEEDS 10개(단, beam-wp bare는 시드를 안 읽으므로 1회만 — beam-wp가
SEED_SENSITIVE_SOLVERS에 없는 것과 동일한 규칙, run_all_scenarios.py::_scenario_tasks 참고).

Beam-Waypoint+VNS(3 beam_width x 3 shake_level = 9configs)가 전체 그리드의 약 76%를
차지해 단일 실행이 너무 길다(추정 약 7시간). --chunk로 4등분했다:
    A  : beam-wp + beam-wp-alns + grasp-wp-alns (VNS 제외 전부) — 추정 약 1.7시간
    B1 : beam-wp-vns, beam_width=4  (shake_level 3종) — 추정 약 1.8시간
    B2 : beam-wp-vns, beam_width=8  (shake_level 3종) — 추정 약 1.8시간
    B3 : beam-wp-vns, beam_width=16 (shake_level 3종) — 추정 약 1.8시간
쪼갠 이유는 속도가 아니라 재개 가능성이다 — 6워커 컴퓨터의 총 작업량은 그대로라 4개를
전부 돌리면 합쳐서 약 7시간이며, 청크 하나하나가 독립적으로 체크포인트되어 세션이
끊겨도 그 청크까지는 남는다(density_stratified 1단계 실행이 두 번 끊겼던 전례 참고).

실행:
    python -m benchmarks.run_refinement_tuning_sweep --chunk A
    python -m benchmarks.run_refinement_tuning_sweep --chunk B1
    python -m benchmarks.run_refinement_tuning_sweep --chunk B2
    python -m benchmarks.run_refinement_tuning_sweep --chunk B3
    python -m benchmarks.run_refinement_tuning_sweep --chunk A --dry-run   # 실행 수만 계산
"""

import argparse
import multiprocessing
import time

import pandas as pd

from benchmarks.benchmark import _load_default_graph, SEED_SENSITIVE_SOLVERS, SOLVER_REGISTRY
from benchmarks.config import BENCHMARK_SEEDS, DEFAULT_TIME_BUDGET_SEC
from benchmarks.results import RESULT_COLUMNS, failed_row, run_solver_task
from benchmarks.run_metadata import save_run_metadata
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.scoring.scoring_engine import precompute_scoring_features
from src.route_engine.weighted_cost_runtime import attach_weighted_cost, prepare_weighted_cost

NUM_WAYPOINTS = 4
TARGET_KMS = [3.0, 7.0]

# circular_density_stratified.json과 동일 좌표(층당 1개 — 노브 유효성도 이 좌표들 기준으로
# 확인했다: bukhan/7km/N=4).
TUNING_STARTS = {
    "hongdae": ("dense", 37.557192, 126.925381),
    "gyeongbok": ("medium", 37.575771, 126.973297),
    "namsan": ("sparse", 37.551169, 126.988227),
    "bukhan": ("rural", 37.663000, 127.011000),
}

TIMEOUT_SEC = 600.0
CHECKPOINT_EVERY = 25


def _beam_width_values():
    return (4, 8, 16)


def _chunk_a():
    configs = [("beam-wp", {"beam_width": w}) for w in _beam_width_values()]
    configs += [
        ("beam-wp-alns", {"beam_width": w, "alns_removal_fraction": rf})
        for w in _beam_width_values()
        for rf in (0.2, 0.4, 0.6)
    ]
    configs += [("grasp-wp-alns", {"alns_iterations": it}) for it in (10, 20, 30)]
    return configs


def _chunk_b(beam_width):
    return [
        ("beam-wp-vns", {"beam_width": beam_width, "vns_max_shake_level": level})
        for level in (2, 3, 4)
    ]


CHUNKS = {
    "A": _chunk_a(),
    "B1": _chunk_b(4),
    "B2": _chunk_b(8),
    "B3": _chunk_b(16),
}

_POOL_GRAPH = None
# 주의: 워커가 처리하는 모든 태스크가 이 전역을 재사용한다 — 그래프를 변형하는 engine을
# 추가한다면 자체 G.copy()가 있는지 반드시 확인할 것(규칙은 benchmark.py 모듈 docstring
# "그래프 공유·변형 규칙" 참고).


def _pool_worker_init():
    global _POOL_GRAPH
    _POOL_GRAPH = _load_default_graph()
    precompute_scoring_features(_POOL_GRAPH)
    # 프로덕션 dependencies.py::init_route_service()와 동일한 1회성 준비(#462) —
    # 워커가 곧바로 cost_context(WeightedEdgeCost)를 만들 수 있도록 적재율을 붙여 둔다.
    attach_weighted_cost(_POOL_GRAPH, prepare_weighted_cost(
        _POOL_GRAPH, enabled=True, coverage_min_ratio=0.95,
    ))


def _pool_worker_task(algo_key: str, start_node, target_km: float, knobs: dict, seed) -> dict:
    params = {
        "target_km": target_km,
        "num_waypoints": NUM_WAYPOINTS,
        "time_budget_sec": DEFAULT_TIME_BUDGET_SEC,
        **knobs,
    }
    if seed is not None:
        params["seed"] = seed
    return run_solver_task(SOLVER_REGISTRY[algo_key], _POOL_GRAPH, start_node, start_node, params)


def _seed_plan(algo_key: str) -> list:
    return list(BENCHMARK_SEEDS) if algo_key in SEED_SENSITIVE_SOLVERS else [None]


def _resolve_starts(graph) -> dict:
    utils = PathUtils(graph)
    return {
        start_id: (tier, utils.find_nearest_node(lat, lon))
        for start_id, (tier, lat, lon) in TUNING_STARTS.items()
    }


def _build_conditions(chunk_configs: list, resolved_starts: dict) -> list:
    conditions = []
    for start_id, (tier, start_node) in resolved_starts.items():
        for target_km in TARGET_KMS:
            for algo_key, knobs in chunk_configs:
                for seed in _seed_plan(algo_key):
                    conditions.append({
                        "start_id": start_id, "tier": tier, "start_node": start_node,
                        "target_km": target_km, "algo_key": algo_key, "knobs": knobs, "seed": seed,
                    })
    return conditions


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--chunk", choices=list(CHUNKS), required=True)
    parser.add_argument("--dry-run", action="store_true", help="실행하지 않고 총 실행 수만 계산")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    chunk_configs = CHUNKS[args.chunk]
    n_conditions = len(TUNING_STARTS) * len(TARGET_KMS)
    total = sum(n_conditions * len(_seed_plan(algo_key)) for algo_key, _ in chunk_configs)
    print(
        f"chunk={args.chunk}: 출발지 {len(TUNING_STARTS)} x 거리 {len(TARGET_KMS)} x "
        f"설정 {len(chunk_configs)}개 = 총 {total}회",
        flush=True,
    )
    if args.dry_run:
        return

    graph = _load_default_graph()  # 부모 프로세스: find_nearest_node 해석에만 사용
    resolved_starts = _resolve_starts(graph)
    conditions = _build_conditions(chunk_configs, resolved_starts)

    print("워커 풀 준비 중...", flush=True)
    t0 = time.perf_counter()
    pool = multiprocessing.get_context("spawn").Pool(processes=args.workers, initializer=_pool_worker_init)
    print(f"워커 풀 준비 완료: {time.perf_counter() - t0:.1f}초", flush=True)

    t_start = time.perf_counter()
    async_results = [
        (cond, pool.apply_async(
            _pool_worker_task,
            args=(cond["algo_key"], cond["start_node"], cond["target_km"], cond["knobs"], cond["seed"]),
        ))
        for cond in conditions
    ]

    out_path = f"benchmarks/refinement_tuning_{args.chunk}_results.csv"
    columns = ["start_id", "tier", "algo_key", "knobs", "target_km", "num_waypoints", "seed", *RESULT_COLUMNS]

    rows = []
    for i, (cond, ar) in enumerate(async_results, 1):
        solver = SOLVER_REGISTRY[cond["algo_key"]]
        try:
            row = ar.get(timeout=TIMEOUT_SEC)
        except multiprocessing.TimeoutError:
            row = failed_row(solver, "timeout", TIMEOUT_SEC, f"timeout after {TIMEOUT_SEC}s",
                              cond["target_km"], circular=True)
        row["start_id"] = cond["start_id"]
        row["tier"] = cond["tier"]
        row["algo_key"] = cond["algo_key"]
        row["knobs"] = str(cond["knobs"])
        row["target_km"] = cond["target_km"]
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
        out_path, runner=f"run_refinement_tuning_sweep(chunk={args.chunk})",
        chunk=args.chunk, chunk_configs=chunk_configs, tuning_starts=TUNING_STARTS,
        target_kms=TARGET_KMS, num_waypoints=NUM_WAYPOINTS, seeds=BENCHMARK_SEEDS,
        workers=args.workers, timeout_sec=TIMEOUT_SEC, time_budget_sec=DEFAULT_TIME_BUDGET_SEC,
    )

    print(f"\n전체 소요 시간: {time.perf_counter() - t_start:.1f}초")
    print(f"결과 저장 완료: {out_path}")
    print(f"메타데이터 저장 완료: {meta_path}\n")

    print("=== algo_key x knobs 요약 ===")
    summary = result_df.groupby(["algo_key", "knobs"]).agg(
        시도횟수=("status", "count"),
        성공=("status", lambda s: (s == "ok").sum()),
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
