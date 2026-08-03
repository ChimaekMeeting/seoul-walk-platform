# run_all_scenarios.py

import json
import time

import pandas as pd

from benchmarks.config import ROUTE_ENGINE_DATASET
from benchmarks.benchmark import _load_default_graph, run_benchmark, SOLVER_REGISTRY
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.engines.oneway_astar import precompute_landmarks

# ONEWAY_ALGOS   = ["beam-oneway", "grasp-oneway", "alns-oneway", "rcsp-oneway", "plateau", "astar-oneway", "dijkstra-oneway"]
# CIRCULAR_ALGOS = ["beam-circular", "grasp-circular", "alns-circular", "rcsp-circular"]

ONEWAY_ALGOS   = ["astar-oneway", "dijkstra-oneway"]
CIRCULAR_ALGOS = []

def main():
    print("그래프 로딩 중...", flush=True)
    t0 = time.perf_counter()
    graph = _load_default_graph()
    print(f"그래프 로딩 완료: {time.perf_counter() - t0:.1f}초, 노드 {graph.number_of_nodes()}개, 엣지 {graph.number_of_edges()}개", flush=True)

    print("랜드마크 전처리 중...", flush=True)
    t_lm = time.perf_counter()
    precompute_landmarks(graph)
    print(f"랜드마크 전처리 완료: {time.perf_counter() - t_lm:.1f}초", flush=True)
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
        solvers = [SOLVER_REGISTRY[key] for key in algos]

        start_node = utils.find_nearest_node(case["start_lat"], case["start_lon"])
        if mode == "oneway":
            target_node = utils.find_nearest_node(case["end_lat"], case["end_lon"])
        else:
            target_node = start_node

        print(f"[{i}/{len(scenarios)}] {case['id']} ({mode}, profile={case['profile']}, target_km={case['target_km']}) 시작...", flush=True)

        params = {"target_km": case["target_km"], "profile": case["profile"]}
        df = run_benchmark(solvers, graph, start_node, target_node, params, timeout_sec=30.0)
        df.insert(0, "scenario_id", case["id"])
        df.insert(1, "mode", mode)
        all_rows.append(df)

        ok_count = (df["status"] == "ok").sum()
        print(f"  -> {ok_count}/{len(df)} ok", flush=True)

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
        평균거리편차km=("distance_deviation_km", "mean"),
        평균우회도=("overlap_ratio", "mean"),
        평균자기중복=("edge_overlap_ratio", "mean"),
    ).round(3)

    print(summary.to_string())
    
    TARGET_AGNOSTIC_ALGOS = {"A*(oneway)", "Dijkstra(oneway)"}  # target_km을 안 쓰는 순수 최단경로 solver
    hit = TARGET_AGNOSTIC_ALGOS & set(summary.index)
    if hit:
        print(
            f"\n[참고] {', '.join(sorted(hit))}는 target_km을 고려하지 않고 순수 최단경로만 구합니다. "
            "위 표의 평균거리편차km은 이 알고리즘들에겐 '목표 거리 달성도'가 아니라 출발-도착 간 "
            "자연 최단거리와 target_km의 우연한 차이일 뿐이므로, 우회 계열 solver와 나란히 비교하지 마세요."
        )



if __name__ == "__main__":
    main()
