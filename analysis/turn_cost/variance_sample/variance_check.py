"""
현재 활성 순환 엔진 9종의 반복 실행 분산 확인.

benchmarks/benchmark.py::SEED_SENSITIVE_SOLVERS(2026-09-16 기준)에 따르면 seed를
실제로 읽는 건 grasp-wp-*(4종)와 beam-wp-local/vnd/vns/alns(4종) = 8종이고,
beam-wp(순수 beam search, 정제 없음)만 시드 불변이다. 그래서:
  - seed-sensitive 8종: 대표 시나리오 3개(짧음/중간/김) × 서로 다른 seed 3개(같은
    프로세스 반복이 아니라 실제로 값을 바꿔가며) 실행해 진짜 분산을 본다.
  - beam-wp: seed를 바꿔도 같은지 2회만 확인(결정성 재확인 목적).
"""
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from benchmarks.benchmark import _load_default_graph, SOLVER_REGISTRY, SEED_SENSITIVE_SOLVERS
from benchmarks.run_all_scenarios import CIRCULAR_ALGOS
from src.route_engine.scoring.scoring_engine import precompute_scoring_features
from src.route_engine.engines.path_utils import PathUtils

SEEDS = [42, 7, 123]
SAMPLE_SCENARIO_IDS = ["circular_20", "circular_11", "circular_01"]  # 짧음/중간/김


def main():
    print("그래프 로딩 중...", flush=True)
    g = _load_default_graph()
    precompute_scoring_features(g)
    utils = PathUtils(g)

    with open(REPO_ROOT / "benchmarks" / "datasets" / "route_engine.json", encoding="utf-8") as f:
        dataset = json.load(f)
    scenarios = {s["id"]: s for s in dataset["scenarios"]}
    sample = [scenarios[sid] for sid in SAMPLE_SCENARIO_IDS]

    seed_sensitive = [a for a in CIRCULAR_ALGOS if a in SEED_SENSITIVE_SOLVERS]
    deterministic = [a for a in CIRCULAR_ALGOS if a not in SEED_SENSITIVE_SOLVERS]
    print(f"seed-sensitive({len(seed_sensitive)}): {seed_sensitive}")
    print(f"결정적으로 분류된 엔진({len(deterministic)}): {deterministic}", flush=True)

    rows = []
    t_start = time.time()

    for sc in sample:
        start_node = utils.find_nearest_node(sc["start_lat"], sc["start_lon"])
        for algo in seed_sensitive:
            for seed in SEEDS:
                params = {"target_km": sc["target_km"], "seed": seed}
                t0 = time.time()
                try:
                    r = SOLVER_REGISTRY[algo].solve(g, start_node, start_node, params)
                    path = r["paths"][0]
                    elapsed = time.time() - t0
                    closed = len(path) > 1 and path[0] == path[-1]
                    metrics = utils.turn_metrics(path, closed=closed)
                    rows.append({
                        "scenario_id": sc["id"], "algorithm": algo, "seed": seed,
                        "success": True, "runtime_sec": round(elapsed, 2), "num_nodes": len(path),
                        "total_turn_deg": round(metrics.total_turn_deg, 1),
                        "turn_deg_per_km": round(metrics.turn_deg_per_km, 2) if metrics.turn_deg_per_km else None,
                    })
                except Exception as e:
                    rows.append({
                        "scenario_id": sc["id"], "algorithm": algo, "seed": seed,
                        "success": False, "runtime_sec": round(time.time() - t0, 2), "num_nodes": None,
                        "total_turn_deg": None, "turn_deg_per_km": None,
                    })
                print(f"[{sc['id']}/{algo}/seed{seed}] 완료 (누적 {time.time()-t_start:.0f}초)", flush=True)

        for algo in deterministic:
            params = {"target_km": sc["target_km"], "seed": 42}
            paths = []
            for _ in range(2):
                r = SOLVER_REGISTRY[algo].solve(g, start_node, start_node, params)
                paths.append(r["paths"][0])
            same = paths[0] == paths[1]
            metrics = utils.turn_metrics(paths[0], closed=(paths[0][0] == paths[0][-1]))
            rows.append({
                "scenario_id": sc["id"], "algorithm": algo, "seed": "n/a(결정적)",
                "success": True, "runtime_sec": None, "num_nodes": len(paths[0]),
                "total_turn_deg": round(metrics.total_turn_deg, 1),
                "turn_deg_per_km": round(metrics.turn_deg_per_km, 2) if metrics.turn_deg_per_km else None,
                "two_runs_identical": same,
            })
            print(f"[{sc['id']}/{algo}] 결정성 확인: 2회 동일={same} (누적 {time.time()-t_start:.0f}초)", flush=True)

    df = pd.DataFrame(rows)
    out_csv = Path(__file__).parent / "variance_results.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    print("\n=== seed-sensitive 8종: 시나리오x엔진별 seed 간 분산 ===", flush=True)
    ss = df[df["algorithm"].isin(seed_sensitive)]
    summary = ss.groupby(["scenario_id", "algorithm"]).agg(
        n=("total_turn_deg", "count"),
        mean_total=("total_turn_deg", "mean"),
        std_total=("total_turn_deg", "std"),
        min_total=("total_turn_deg", "min"),
        max_total=("total_turn_deg", "max"),
    ).round(2)
    print(summary.to_string(), flush=True)

    print("\n=== 엔진별 seed 간 총 변동폭(3개 시나리오 통합, std=0이면 seed 무관하게 결정적) ===", flush=True)
    algo_summary = ss.groupby("algorithm").agg(
        n=("total_turn_deg", "count"),
        std_total=("total_turn_deg", "std"),
        std_turn_per_km=("turn_deg_per_km", "std"),
    ).round(3)
    print(algo_summary.to_string(), flush=True)

    print("\n=== 결정적으로 분류된 엔진(beam-wp) 2회 동일성 ===", flush=True)
    det = df[df["algorithm"].isin(deterministic)]
    if len(det):
        print(det[["scenario_id", "algorithm", "two_runs_identical"]].to_string(index=False), flush=True)

    print(f"\n총 소요 시간: {time.time()-t_start:.0f}초, 결과 저장: {out_csv}", flush=True)


if __name__ == "__main__":
    main()
