"""
benchmarks/run_alns_validation.py

GRASP+ALNS 검수 요청서(2026-08-30) §7이 요구하는 다중 조건 검증 러너.
run_min_separation_validation.py와 같은 seed×target_km×start_node 격자에서
grasp-wp-alns만 실행한다 — Local/VND/VNS/grasp-circular는 이미 그 스크립트가 같은
격자로 실행 중이라 중복 실행하지 않는다. 두 CSV는 (seed, start_node, target_km) 키로
합쳐서 비교할 수 있다.

실행:
    python -m benchmarks.run_alns_validation
"""

import multiprocessing
import time

import pandas as pd

from benchmarks.benchmark import (
    RESULT_COLUMNS,
    SOLVER_REGISTRY,
    _compute_edge_overlap_ratio,
    _compute_route_distance_km,
    _count_spikes,
    _failed_row,
    _is_closed_loop,
    _load_default_graph,
    _validate_solver_result,
)
from src.route_engine.scoring.scoring_engine import precompute_scoring_features

SEEDS = [42, 7, 123]
TARGET_KMS = [3.0, 5.0]
START_NODES = [1, 41417, 111383, 175895, 179044]  # run_min_separation_validation.py와 동일 노드
ALGOS = ["grasp-wp-alns"]
TIMEOUT_SEC = 300.0

_POOL_GRAPH = None
# 주의(2026-08-30): 워커가 처리하는 모든 조합이 이 전역을 그대로 재사용한다 — 그래프를
# 변형하는 engine을 추가한다면 자체 G.copy()가 있는지 반드시 확인할 것(규칙은
# benchmarks/benchmark.py 모듈 docstring "그래프 공유·변형 규칙" 참고).


def _pool_worker_init():
    global _POOL_GRAPH
    _POOL_GRAPH = _load_default_graph()
    precompute_scoring_features(_POOL_GRAPH)


def _pool_worker_task(solver_key: str, start_node: int, target_km: float, seed: int) -> dict:
    solver = SOLVER_REGISTRY[solver_key]
    params = {"target_km": target_km, "seed": seed}

    t0 = time.perf_counter()
    try:
        raw_result = solver.solve(_POOL_GRAPH, start_node, start_node, params)
    except Exception as e:
        return _failed_row(solver, "failed", time.perf_counter() - t0, repr(e), target_km)

    elapsed = time.perf_counter() - t0

    try:
        result = _validate_solver_result(raw_result)
    except Exception as e:
        return _failed_row(solver, "failed", elapsed, str(e), target_km)

    distance_km = _compute_route_distance_km(_POOL_GRAPH, result["paths"])
    distance_deviation_km = (
        round(abs(distance_km - target_km), 4) if distance_km is not None and target_km is not None else None
    )

    return {
        "algorithm": solver.name,
        "status": "ok",
        "elapsed_sec": round(elapsed, 6),
        "within_time_budget": None,
        "cost": result["cost"],
        "overlap_ratio": result["overlap_ratio"],
        "distance_km": distance_km,
        "target_km": target_km,
        "distance_deviation_km": distance_deviation_km,
        "is_closed_loop": _is_closed_loop(result["paths"]),
        "spike_count": _count_spikes(result["paths"]),
        "edge_overlap_ratio": _compute_edge_overlap_ratio(result["paths"]),
        "find_path_sec": result.get("find_path_sec"),
        "astar_calls": result.get("astar_calls"),
        "cache_hits": result.get("cache_hits"),
        "selection_status": result.get("selection_status"),
        "feasible": result.get("feasible"),
        "segment_p1_p2_m": result.get("segment_p1_p2_m"),
        "segment_p2_p3_m": result.get("segment_p2_p3_m"),
        "segment_p3_p1_m": result.get("segment_p3_p1_m"),
        "waypoint_separation_m": result.get("waypoint_separation_m"),
        "min_waypoint_separation_m": result.get("min_waypoint_separation_m"),
        "repeated_edge_ratio": (
            result.get("repeated_edge_ratio")
            if result.get("repeated_edge_ratio") is not None
            else _compute_edge_overlap_ratio(result["paths"])
        ),
        "waypoint_angle_diff_deg": result.get("waypoint_angle_diff_deg"),
        "segment_balance_ratio": result.get("segment_balance_ratio"),
        "is_degenerate_loop": result.get("is_degenerate_loop"),
        "alns_operator_stats": result.get("alns_operator_stats"),
        "error": "",
    }


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
            row = _failed_row(solver, "timeout", TIMEOUT_SEC, f"timeout after {TIMEOUT_SEC}s", target_km)
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
            "benchmarks/alns_validation_results.csv", index=False,
        )

    pool.close()
    pool.join()

    result_df = pd.DataFrame(rows, columns=["seed", "start_node", *RESULT_COLUMNS])
    out_path = "benchmarks/alns_validation_results.csv"
    result_df.to_csv(out_path, index=False)

    print(f"\n전체 소요 시간: {time.perf_counter() - t_start:.1f}초")
    print(f"결과 저장 완료: {out_path}\n")

    print("=== 요약 ===")
    print(f"시도 {len(result_df)}건, 성공 {(result_df['status']=='ok').sum()}건, "
          f"feasible {(result_df['feasible']==True).sum()}건")
    print(f"평균 elapsed_sec: {result_df['elapsed_sec'].mean():.1f}, 최대: {result_df['elapsed_sec'].max():.1f}")
    print(f"평균 edge_overlap_ratio: {result_df['edge_overlap_ratio'].mean():.4f}")
    violations = result_df[
        result_df["waypoint_separation_m"].notna()
        & result_df["min_waypoint_separation_m"].notna()
        & (result_df["waypoint_separation_m"] < result_df["min_waypoint_separation_m"])
    ]
    print(f"P2-P3 최소거리 위반 건수: {len(violations)}건")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] [%(name)s] %(message)s")
    main()
