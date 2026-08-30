"""
benchmarks/run_min_separation_validation.py

P2-P3 최소거리 안전장치("Claude CLI 전달용 구현 지시서: 현재 구현을 유지한 상태에서
P2-P3 최소거리와 추가 검증만 반영", 2026-08-30) §7이 요구하는 다중 조건 검증 러너.

seed × target_km × start_node 조합마다 grasp-wp-local/vnd/vns와 비교 기준(grasp-circular)을
동일 조건에서 실행하고, 결과를 원본 CSV(반올림 없는 값 그대로)로 저장한다. run_all_scenarios.py
와 달리 고정 시나리오 데이터셋(JSON)이 아니라 이 스크립트 자체가 정의하는 seed/target_km/
start_node 격자를 순회한다.

범위 축소 근거(요청서 §7 "가능하면 7km"는 선택 사항으로 명시돼 있음):
    target_km=7.0은 생략했다 — VNS가 target_km=5.0 1회에 약 230~250초가 걸려(2026-08-30
    실측), 7km까지 포함하면 전체 매트릭스가 감당하기 어려운 시간으로 늘어난다. 대신
    target_km=3.0/5.0에서 먼저 안정성을 확인하고, 필요하면 7km는 별도로 추가 실행한다.

실행:
    python -m benchmarks.run_min_separation_validation
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
START_NODES = [1, 41417, 111383, 175895, 179044]  # largest_cc(=전체 그래프)에서 seed=2026으로 무작위 추출
ALGOS = ["grasp-wp-local", "grasp-wp-vnd", "grasp-wp-vns", "grasp-circular"]  # grasp-circular = 기존 비교 기준
TIMEOUT_SEC = 400.0  # VNS가 target_km=5.0에서 최대 250초 안팎 걸리는 것을 감안한 여유

_POOL_GRAPH = None
# 주의(2026-08-30): 워커가 처리하는 모든 조합(seed×target_km×start_node×algo)이 이
# 전역을 그대로 재사용한다 — 그래프를 변형하는 engine을 추가한다면 자체 G.copy()가
# 있는지 반드시 확인할 것(규칙은 benchmarks/benchmark.py 모듈 docstring "그래프
# 공유·변형 규칙" 참고).


def _pool_worker_init():
    global _POOL_GRAPH
    _POOL_GRAPH = _load_default_graph()
    precompute_scoring_features(_POOL_GRAPH)


def _pool_worker_task(solver_key: str, start_node: int, target_km: float, seed: int) -> dict:
    """단일 (solver, start_node, target_km, seed) 조합 실행. benchmark.py::_run_single과
    동일한 결과 스키마(신규 selection_status/segment_* 필드 포함)를 만든다 — 그 함수를
    그대로 재사용하지 않는 이유는 이 스크립트가 프로세스 풀(워커당 그래프 1회 로드)
    구조를 쓰기 때문이다(run_all_scenarios.py와 동일한 이유)."""
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
        # 중간 저장 — 장시간 실행 도중 중단돼도 그때까지 결과는 보존한다.
        pd.DataFrame(rows, columns=["seed", "start_node", *RESULT_COLUMNS]).to_csv(
            "benchmarks/min_separation_validation_results.csv", index=False,
        )

    pool.close()
    pool.join()

    result_df = pd.DataFrame(rows, columns=["seed", "start_node", *RESULT_COLUMNS])
    out_path = "benchmarks/min_separation_validation_results.csv"
    result_df.to_csv(out_path, index=False)

    print(f"\n전체 소요 시간: {time.perf_counter() - t_start:.1f}초")
    print(f"결과 저장 완료: {out_path}\n")

    print("=== 알고리즘별 요약 ===")
    summary = result_df.groupby("algorithm").agg(
        시도횟수=("status", "count"),
        성공=("status", lambda s: (s == "ok").sum()),
        feasible비율=("feasible", lambda s: s.mean() if s.notna().any() else None),
        평균초=("elapsed_sec", "mean"),
        최대초=("elapsed_sec", "max"),
        평균거리편차km=("distance_deviation_km", "mean"),
        평균자기중복=("edge_overlap_ratio", "mean"),
        최소거리위반건수=("waypoint_separation_m", lambda s: None),  # 아래에서 별도 계산
    ).round(4)
    print(summary.to_string())

    # P2-P3 최소거리 위반 건수(요청서 §7.2 성공판정 3번: 위반 0건이어야 함)
    grasp_wp_rows = result_df[result_df["algorithm"].str.startswith("GRASP-Waypoint", na=False)]
    violations = grasp_wp_rows[
        grasp_wp_rows["waypoint_separation_m"].notna()
        & grasp_wp_rows["min_waypoint_separation_m"].notna()
        & (grasp_wp_rows["waypoint_separation_m"] < grasp_wp_rows["min_waypoint_separation_m"])
    ]
    print(f"\nP2-P3 최소거리 위반 건수: {len(violations)}건 (grasp-wp-* 중 feasible/fallback으로 실제 경로가 나온 행 기준)")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] [%(name)s] %(message)s")
    main()
