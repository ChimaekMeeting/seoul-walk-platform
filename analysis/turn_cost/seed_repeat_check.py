"""
확률적 순환 엔진 3종(grasp-wp-alns, beam-wp-alns, beam-wp-vns)의 다중 seed 반복 측정.

variance_sample/variance_check.py(대표 시나리오 3개 x seed 3개)에서 이 3종이
seed에 따라 실제로 값이 크게 달라짐을 확인했다. turn_cost_distribution.csv의
"엔진별 회전량 통계" 표는 이 3종에 대해 seed=42 단 1회 관측값이라 대표값으로
쓰기 부적절하다 — 이 스크립트는 25개 시나리오 전수 x
benchmarks/config.py::BENCHMARK_SEEDS(팀이 이미 분산 추정용으로 정해둔 10개
시드) 조합으로 평균·표준편차를 구해 대표값을 만든다.

실행: python analysis/turn_cost/seed_repeat_check.py (레포 루트에서)
출력: seed_repeat_results.csv (이 스크립트와 같은 디렉터리)
"""
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from benchmarks.benchmark import _load_default_graph, SOLVER_REGISTRY
from benchmarks.config import BENCHMARK_SEEDS
from src.route_engine.scoring.scoring_engine import precompute_scoring_features
from src.route_engine.engines.path_utils import PathUtils

STOCHASTIC_ALGOS = ["grasp-wp-alns", "beam-wp-alns", "beam-wp-vns"]


def main():
    print("그래프 로딩 중...", flush=True)
    g = _load_default_graph()
    precompute_scoring_features(g)
    utils = PathUtils(g)

    with open(REPO_ROOT / "benchmarks" / "datasets" / "route_engine.json", encoding="utf-8") as f:
        dataset = json.load(f)
    scenarios = [s for s in dataset["scenarios"] if s["mode"] == "circular"]
    print(f"순환 시나리오 {len(scenarios)}개 x 확률적 엔진 {STOCHASTIC_ALGOS} x seed {len(BENCHMARK_SEEDS)}개 "
          f"= 최대 {len(scenarios) * len(STOCHASTIC_ALGOS) * len(BENCHMARK_SEEDS)}회", flush=True)

    rows = []
    t_start = time.time()
    for i, sc in enumerate(scenarios, 1):
        start_node = utils.find_nearest_node(sc["start_lat"], sc["start_lon"])
        target_km = sc["target_km"]

        for algo in STOCHASTIC_ALGOS:
            for seed in BENCHMARK_SEEDS:
                params = {"target_km": target_km, "seed": seed}
                try:
                    r = SOLVER_REGISTRY[algo].solve(g, start_node, start_node, params)
                    path = r["paths"][0]
                except Exception as e:
                    print(f"  [{sc['id']}/{algo}/seed{seed}] FAILED: {e!r}", flush=True)
                    continue
                if not path:
                    continue
                closed = len(path) > 1 and path[0] == path[-1]
                metrics = utils.turn_metrics(path, closed=closed)
                rows.append({
                    "scenario_id": sc["id"], "algorithm": algo, "seed": seed, "target_km": target_km,
                    "num_nodes": len(path),
                    "total_turn_deg": round(metrics.total_turn_deg, 1),
                    "max_turn_deg": round(metrics.max_turn_deg, 1),
                    "turn_deg_per_km": round(metrics.turn_deg_per_km, 2) if metrics.turn_deg_per_km is not None else None,
                })

        print(f"[{i}/{len(scenarios)}] {sc['id']} 완료 (누적 {time.time()-t_start:.0f}초)", flush=True)

    df = pd.DataFrame(rows)
    out_path = Path(__file__).parent / "seed_repeat_results.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n총 소요 시간: {time.time()-t_start:.0f}초, 결과 {len(df)}행 저장: {out_path}", flush=True)

    print("\n=== 엔진별 대표값(25개 시나리오 x 10개 시드 통합) ===", flush=True)
    summary = df.groupby("algorithm").agg(
        n=("total_turn_deg", "count"),
        평균거리당회전량=("turn_deg_per_km", "mean"),
        표준편차=("turn_deg_per_km", "std"),
        최소=("turn_deg_per_km", "min"),
        최대=("turn_deg_per_km", "max"),
        평균최대회전각=("max_turn_deg", "mean"),
    ).round(2)
    print(summary.to_string(), flush=True)

    print("\n=== 참고: seed=42만 썼을 때 값(기존 turn_cost_distribution.csv 값과 비교용) ===", flush=True)
    seed42 = df[df["seed"] == 42].groupby("algorithm")["turn_deg_per_km"].mean().round(2)
    print(seed42.to_string(), flush=True)


if __name__ == "__main__":
    main()
