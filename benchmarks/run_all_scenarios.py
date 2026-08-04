# run_all_scenarios.py

import json
import multiprocessing
import time

import pandas as pd

from benchmarks.config import ROUTE_ENGINE_DATASET
from benchmarks.benchmark import (
    _load_default_graph,
    _failed_row,
    _validate_solver_result,
    _compute_route_distance_km,
    _is_closed_loop,
    _count_spikes,
    _compute_edge_overlap_ratio,
    RESULT_COLUMNS,
    SOLVER_REGISTRY,
)
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.engines.oneway_astar import precompute_landmarks
from src.route_engine.scoring.scoring_engine import precompute_scoring_features

ONEWAY_ALGOS   = ["astar-oneway", "dijkstra-oneway", "bi-astar-oneway", "beam-oneway", "grasp-oneway", "alns-oneway", "rcsp-oneway", "plateau"]
CIRCULAR_ALGOS = ["beam-circular", "grasp-circular", "alns-circular", "rcsp-circular"]

_POOL_GRAPH = None  # 워커 프로세스 전역 — 워커당 1번만 채워짐(그래프 재전송 없음)


def _pool_worker_init():
    """워커 프로세스 시작 시 1회만 실행 — 그래프를 이 워커 메모리 안에 준비."""
    global _POOL_GRAPH
    _POOL_GRAPH = _load_default_graph()
    precompute_landmarks(_POOL_GRAPH)
    precompute_scoring_features(_POOL_GRAPH)


def _pool_worker_task(solver_key: str, start_node, target_node, params: dict) -> dict:
    """
    태스크마다 실행. solver 인스턴스·그래프를 매번 안 받고,
    solver_key로 SOLVER_REGISTRY에서 찾고 그래프는 워커 전역(_POOL_GRAPH)을 그대로 쓴다.
    """
    solver = SOLVER_REGISTRY[solver_key]
    target_km = params.get("target_km")
    time_budget_sec = params.get("time_budget_sec")

    t0 = time.perf_counter()
    try:
        raw_result = solver.solve(_POOL_GRAPH, start_node, target_node, params)
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
    within_time_budget = elapsed <= time_budget_sec if time_budget_sec is not None else None

    return {
        "algorithm": solver.name,
        "status": "ok",
        "elapsed_sec": round(elapsed, 6),
        "within_time_budget": within_time_budget,
        "cost": result["cost"],
        "overlap_ratio": result["overlap_ratio"],
        "distance_km": distance_km,
        "target_km": target_km,
        "distance_deviation_km": distance_deviation_km,
        "is_closed_loop": _is_closed_loop(result["paths"]),
        "spike_count": _count_spikes(result["paths"]),
        "edge_overlap_ratio": _compute_edge_overlap_ratio(result["paths"]),
        "find_path_sec": result.get("find_path_sec"),
        "error": "",
    }


def _run_scenario_with_pool(pool, algos, start_node, target_node, params, timeout_sec=30.0) -> pd.DataFrame:
    """
    이미 떠 있는 워커 풀에 알고리즘별 태스크를 제출하고 결과를 모은다.
    타임아웃 시 해당 워커는 죽이지 않고 결과만 실패 처리한다(하드킬 포기 — 절충안).
    """
    async_results = {
        key: pool.apply_async(_pool_worker_task, args=(key, start_node, target_node, params))
        for key in algos
    }
    rows = []
    for key, ar in async_results.items():
        solver = SOLVER_REGISTRY[key]
        try:
            rows.append(ar.get(timeout=timeout_sec))
        except multiprocessing.TimeoutError:
            rows.append(_failed_row(
                solver, "timeout", timeout_sec,
                f"timeout after {timeout_sec}s (worker 강제종료 안 함 — 절충안)", params.get("target_km"),
            ))
    return pd.DataFrame(rows, columns=RESULT_COLUMNS)


def main():
    print("워커 풀 준비 중...", flush=True)
    t0 = time.perf_counter()
    pool = multiprocessing.get_context("spawn").Pool(processes=6, initializer=_pool_worker_init)
    print(f"워커 풀 준비 완료: {time.perf_counter() - t0:.1f}초", flush=True)

    graph = _load_default_graph()  # 부모 프로세스에선 노드 탐색(find_nearest_node)에만 사용
    utils = PathUtils(graph)

    with open(ROUTE_ENGINE_DATASET, encoding="utf-8") as f:
        dataset = json.load(f)

    scenarios = dataset["scenarios"]
    print(f"시나리오 {len(scenarios)}개 테스트 (oneway {sum(1 for s in scenarios if s['mode']=='oneway')}개, circular {sum(1 for s in scenarios if s['mode']=='circular')}개)\n", flush=True)

    all_rows = []
    t_start = time.perf_counter()

    for i, case in enumerate(scenarios, 1):
        mode = case["mode"]
        algos = ONEWAY_ALGOS if mode == "oneway" else CIRCULAR_ALGOS
        if not algos:
            continue

        start_node = utils.find_nearest_node(case["start_lat"], case["start_lon"])
        target_node = utils.find_nearest_node(case["end_lat"], case["end_lon"]) if mode == "oneway" else start_node

        print(f"[{i}/{len(scenarios)}] {case['id']} ({mode}, profile={case['profile']}, target_km={case['target_km']}) 시작...", flush=True)

        params = {"target_km": case["target_km"], "profile": case["profile"]}
        df = _run_scenario_with_pool(pool, algos, start_node, target_node, params, timeout_sec=30.0)
        df.insert(0, "scenario_id", case["id"])
        df.insert(1, "mode", mode)
        all_rows.append(df)

        ok_count = (df["status"] == "ok").sum()
        print(f"  -> {ok_count}/{len(df)} ok", flush=True)

    pool.close()
    pool.join()

    result_df = pd.concat(all_rows, ignore_index=True)
    out_path = "all_scenarios_results.csv"
    result_df.to_csv(out_path, index=False)

    print(f"\n전체 소요 시간: {time.perf_counter() - t_start:.1f}초")
    print(f"결과 저장 완료: {out_path}\n")

    print("=== 알고리즘별 요약 ===")
    summary = result_df.groupby("algorithm").agg(
        시도횟수=("status", "count"),
        성공=("status", lambda s: (s == "ok").sum()),
        평균초=("elapsed_sec", "mean"),
        최대초=("elapsed_sec", "max"),
        평균find_path초=("find_path_sec", "mean"),
        평균거리편차km=("distance_deviation_km", "mean"),
        평균우회도=("overlap_ratio", "mean"),
        평균자기중복=("edge_overlap_ratio", "mean"),
    ).round(4)

    print(summary.to_string())

    TARGET_AGNOSTIC_ALGOS = {"A*(oneway)", "Dijkstra(oneway)", "Bidirectional A*(oneway)"}
    hit = TARGET_AGNOSTIC_ALGOS & set(summary.index)
    if hit:
        print(
            f"\n[참고] {', '.join(sorted(hit))}는 target_km을 고려하지 않고 순수 최단경로만 구합니다. "
            "위 표의 평균거리편차km은 이 알고리즘들에겐 '목표 거리 달성도'가 아니라 출발-도착 간 "
            "자연 최단거리와 target_km의 우연한 차이일 뿐이므로, 우회 계열 solver와 나란히 비교하지 마세요."
        )


if __name__ == "__main__":
    main()
