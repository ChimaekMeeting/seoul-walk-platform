"""
확률적 엔진(grasp-wp-local, grasp-circular, alns-circular)의 실행 분산 확인.

전수 25개 시나리오를 반복하지 않고, target_km이 짧은/중간/긴 구간을 고르게
포함하는 대표 시나리오 5개만 골라 각 엔진을 5회씩 반복 실행한다(turn_cost 실제
경로 분포 검증 결과 검토 §8.3 권고 반영).

부수적으로 beam-circular/rcsp-circular가 결정적인지도 같은 시나리오 1개로
간단히 확인한다(같은 입력을 2회 실행해 경로가 완전히 같은지 비교).
"""
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from benchmarks.benchmark import _load_default_graph, SOLVER_REGISTRY
from src.route_engine.scoring.scoring_engine import precompute_scoring_features
from src.route_engine.engines.path_utils import PathUtils

REPEATS = 5
VARIANCE_ALGOS = ["grasp-wp-local", "grasp-circular", "alns-circular"]
# target_km 짧음/중간/김을 고르게 포함 + circular_09(기존 alns 실패 시나리오, 실패 재현성 확인용)
SAMPLE_SCENARIO_IDS = ["circular_20", "circular_02", "circular_11", "circular_01", "circular_09"]


def main():
    print("그래프 로딩 중...", flush=True)
    g = _load_default_graph()
    precompute_scoring_features(g)
    utils = PathUtils(g)

    with open(REPO_ROOT / "benchmarks" / "datasets" / "route_engine.json", encoding="utf-8") as f:
        dataset = json.load(f)
    scenarios = {s["id"]: s for s in dataset["scenarios"]}
    sample = [scenarios[sid] for sid in SAMPLE_SCENARIO_IDS]

    rows = []
    t_start = time.time()
    for sc in sample:
        start_node = utils.find_nearest_node(sc["start_lat"], sc["start_lon"])
        params = {"target_km": sc["target_km"], "profile": sc["profile"]}

        for algo in VARIANCE_ALGOS:
            for rep in range(1, REPEATS + 1):
                t0 = time.time()
                try:
                    r = SOLVER_REGISTRY[algo].solve(g, start_node, start_node, params)
                    path = r["paths"][0]
                    elapsed = time.time() - t0
                    closed = len(path) > 1 and path[0] == path[-1]
                    metrics = utils.turn_metrics(path, closed=closed)
                    rows.append({
                        "scenario_id": sc["id"], "target_km": sc["target_km"], "algorithm": algo,
                        "rep": rep, "success": True, "runtime_sec": round(elapsed, 3),
                        "num_nodes": len(path),
                        "total_turn_deg": round(metrics.total_turn_deg, 1),
                        "max_turn_deg": round(metrics.max_turn_deg, 1),
                        "turn_deg_per_km": round(metrics.turn_deg_per_km, 2) if metrics.turn_deg_per_km else None,
                    })
                except Exception as e:
                    rows.append({
                        "scenario_id": sc["id"], "target_km": sc["target_km"], "algorithm": algo,
                        "rep": rep, "success": False, "runtime_sec": round(time.time() - t0, 3),
                        "num_nodes": None, "total_turn_deg": None, "max_turn_deg": None,
                        "turn_deg_per_km": None,
                    })
                print(f"[{sc['id']}/{algo}/rep{rep}] 완료 (누적 {time.time()-t_start:.0f}초)", flush=True)

    df = pd.DataFrame(rows)
    out_csv = Path(__file__).parent / "variance_results.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    print("\n=== 시나리오x엔진별 분산 (성공 케이스만) ===", flush=True)
    ok = df[df["success"]]
    summary = ok.groupby(["scenario_id", "algorithm"]).agg(
        n=("total_turn_deg", "count"),
        mean_total=("total_turn_deg", "mean"),
        std_total=("total_turn_deg", "std"),
        mean_per_km=("turn_deg_per_km", "mean"),
        std_per_km=("turn_deg_per_km", "std"),
    ).round(2)
    print(summary.to_string(), flush=True)

    print("\n=== 엔진별 전체 요약(5개 시나리오 통합) ===", flush=True)
    algo_summary = ok.groupby("algorithm").agg(
        n=("total_turn_deg", "count"),
        mean_total=("total_turn_deg", "mean"),
        std_total=("total_turn_deg", "std"),
        cv_total_pct=("total_turn_deg", lambda s: 100 * s.std() / s.mean() if s.mean() else None),
    ).round(2)
    print(algo_summary.to_string(), flush=True)

    fail_counts = df[~df["success"]].groupby(["scenario_id", "algorithm"]).size()
    if len(fail_counts):
        print("\n=== 실패 케이스 ===", flush=True)
        print(fail_counts.to_string(), flush=True)

    # beam-circular / rcsp-circular 결정성 간단 확인 (같은 시나리오 2회 비교)
    print("\n=== beam-circular / rcsp-circular 결정성 확인(circular_01, 2회) ===", flush=True)
    check_sc = scenarios["circular_01"]
    check_start = utils.find_nearest_node(check_sc["start_lat"], check_sc["start_lon"])
    check_params = {"target_km": check_sc["target_km"], "profile": check_sc["profile"]}
    for algo in ["beam-circular", "rcsp-circular"]:
        if algo == "beam-circular":
            from src.route_engine.engines.circular_beam import CircularBeamEngine
            from src.route_engine.scoring.scoring_engine import calculate_custom_score
            from src.schema.route_schema import CircularRouteInput

            def run_once():
                inp = CircularRouteInput(start_lat=0.0, start_lon=0.0, target_km=check_sc["target_km"])
                engine = CircularBeamEngine(inp=inp, G=g, custom_weights=None, profile=check_sc["profile"])
                calculate_custom_score(engine.G, {
                    "mode": engine.scoring_mode, "weights": engine.weights, "blocked_tags": engine.blocked_tags,
                })
                return engine.utils.prune_dead_ends(engine.find_path(check_start, check_sc["target_km"])[0])
            p1, p2 = run_once(), run_once()
        else:
            p1 = SOLVER_REGISTRY[algo].solve(g, check_start, check_start, check_params)["paths"][0]
            p2 = SOLVER_REGISTRY[algo].solve(g, check_start, check_start, check_params)["paths"][0]
        print(f"{algo}: 두 실행 경로 동일 = {p1 == p2} (길이 {len(p1)} vs {len(p2)})", flush=True)

    print(f"\n총 소요 시간: {time.time()-t_start:.0f}초, 결과 저장: {out_csv}", flush=True)


if __name__ == "__main__":
    main()
