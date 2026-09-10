"""
benchmarks/run_alns_sweep.py

ALNS 하이퍼파라미터 스윕 러너(2026-09-10 신규, 이슈 F).

지금까지 iterations / cooling_rate / removal_fraction 등은 "기본값은 실험 시작값이며,
서비스 성능을 보장하는 튜닝값이 아니다"(waypoint_alns.ALNSConfig docstring)라고 적힌 채
남아 있었는데, 정작 이 값들을 바꿔가며 재보는 실행 경로가 없었다. 이 러너가 그 격자를
돈다 — 노브는 grasp_waypoint_solver._refinement_options_from_params()가 읽는
alns_* 키로 전달한다.

주의:
    - 한 설정마다 BENCHMARK_SEEDS 전부를 돌린다. ALNS는 확률적이라 시드 1회 결과로
      파라미터를 고르면 우연을 튜닝하게 된다.
    - 결과 해석(평균/표준편차/p95/최악, 게이트 통과율, 짝지은 비교)은 별도 집계
      스크립트(이슈 G)가 맡는다. 이 스크립트는 raw CSV와 참고용 요약만 만든다.
    - SWEEP_GRID는 곱집합이다. 축을 늘리기 전에 반드시 총 실행 수를 확인할 것.

실행:
    python -m benchmarks.run_alns_sweep
"""

import itertools
import multiprocessing
import time

import pandas as pd

from benchmarks.benchmark import _load_default_graph, SOLVER_REGISTRY
from benchmarks.config import BENCHMARK_SEEDS, DEFAULT_TIME_BUDGET_SEC
from benchmarks.results import RESULT_COLUMNS, failed_row, run_solver_task
from src.route_engine.scoring.scoring_engine import precompute_scoring_features

ALGO = "grasp-wp-alns"
TARGET_KMS = [3.0, 5.0]
START_NODES = [1, 41417, 111383, 175895, 179044]  # 다른 격자 러너와 동일 노드
TIMEOUT_SEC = 400.0
CHECKPOINT_EVERY = 25  # 중간 저장 주기(장시간 실행 중 중단돼도 여기까지는 남는다)

# 스윕할 노브와 후보값. 현재: 3 * 3 * 2 = 18개 설정
# × 2 target_km × 5 start_node × 10 seed = 1,800회 실행.
SWEEP_GRID = {
    "alns_iterations": [30, 100, 200],
    "alns_removal_fraction": [0.2, 0.3, 0.5],
    "alns_cooling_rate": [0.90, 0.95],
}

_POOL_GRAPH = None
# 주의: 워커가 처리하는 모든 조합이 이 전역을 그대로 재사용한다 — 그래프를 변형하는
# engine을 추가한다면 자체 G.copy()가 있는지 반드시 확인할 것(규칙은
# benchmarks/benchmark.py 모듈 docstring "그래프 공유·변형 규칙" 참고).


def _pool_worker_init():
    global _POOL_GRAPH
    _POOL_GRAPH = _load_default_graph()
    precompute_scoring_features(_POOL_GRAPH)


def _pool_worker_task(start_node: int, target_km: float, seed: int, knobs: dict) -> dict:
    params = {
        "target_km": target_km,
        "seed": seed,
        "time_budget_sec": DEFAULT_TIME_BUDGET_SEC,
        **knobs,
    }
    return run_solver_task(SOLVER_REGISTRY[ALGO], _POOL_GRAPH, start_node, start_node, params)


def knob_combinations() -> list[dict]:
    """SWEEP_GRID의 곱집합을 params 키 그대로의 dict 목록으로 편다."""
    keys = list(SWEEP_GRID)
    return [dict(zip(keys, values)) for values in itertools.product(*(SWEEP_GRID[k] for k in keys))]


def main():
    knob_sets = knob_combinations()
    conditions = [
        (start_node, target_km, seed, knobs)
        for knobs in knob_sets
        for target_km in TARGET_KMS
        for start_node in START_NODES
        for seed in BENCHMARK_SEEDS
    ]
    print(
        f"설정 {len(knob_sets)}개 × {len(TARGET_KMS)}target_km × {len(START_NODES)}start_node "
        f"× {len(BENCHMARK_SEEDS)}seed = {len(conditions)}회 실행",
        flush=True,
    )

    print("워커 풀 준비 중...", flush=True)
    t0 = time.perf_counter()
    pool = multiprocessing.get_context("spawn").Pool(processes=6, initializer=_pool_worker_init)
    print(f"워커 풀 준비 완료: {time.perf_counter() - t0:.1f}초", flush=True)

    t_start = time.perf_counter()
    async_results = [
        (start_node, target_km, seed, knobs,
         pool.apply_async(_pool_worker_task, args=(start_node, target_km, seed, knobs)))
        for start_node, target_km, seed, knobs in conditions
    ]

    knob_columns = list(SWEEP_GRID)
    columns = ["seed", "start_node", *knob_columns, *RESULT_COLUMNS]
    out_path = "benchmarks/alns_sweep_results.csv"

    rows = []
    for i, (start_node, target_km, seed, knobs, ar) in enumerate(async_results, 1):
        try:
            row = ar.get(timeout=TIMEOUT_SEC)
        except multiprocessing.TimeoutError:
            row = failed_row(
                SOLVER_REGISTRY[ALGO], "timeout", TIMEOUT_SEC,
                f"timeout after {TIMEOUT_SEC}s", target_km, True,
            )
        row["seed"] = seed
        row["start_node"] = start_node
        row.update(knobs)
        rows.append(row)

        if i % CHECKPOINT_EVERY == 0 or i == len(async_results):
            print(f"[{i}/{len(async_results)}] 누적 {time.perf_counter() - t_start:.0f}s", flush=True)
            pd.DataFrame(rows, columns=columns).to_csv(out_path, index=False)

    pool.close()
    pool.join()

    result_df = pd.DataFrame(rows, columns=columns)
    result_df.to_csv(out_path, index=False)

    print(f"\n전체 소요 시간: {time.perf_counter() - t_start:.1f}초")
    print(f"결과 저장 완료: {out_path}\n")

    print("=== 설정별 요약(참고용 — 정식 집계는 별도 스크립트) ===")
    summary = result_df.groupby(knob_columns).agg(
        시도횟수=("status", "count"),
        게이트통과율=("passed", lambda s: s.mean() if s.notna().any() else None),
        평균거리편차km=("distance_deviation_km", "mean"),
        편차표준편차=("distance_deviation_km", "std"),
        최악거리편차km=("distance_deviation_km", "max"),
        평균재통행=("repeated_edge_ratio", "mean"),
        평균원형성=("circularity_q", "mean"),
        평균초=("elapsed_sec", "mean"),
        평균astar호출=("astar_calls", "mean"),
    ).round(4)
    print(summary.to_string())
    print(
        "\n[주의] 평균만 보고 설정을 고르면 '평균은 좋으나 가끔 크게 빗나가는' 설정이 뽑힙니다. "
        "편차표준편차·최악거리편차km·게이트통과율을 함께 보세요."
    )


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] [%(name)s] %(message)s")
    main()
