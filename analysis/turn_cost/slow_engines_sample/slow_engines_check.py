"""
grasp-wp-vnd / grasp-wp-alns / grasp-wp-vns 대표 시나리오 표본 확인.

25개 전수 실행은 1회 소요시간(사전 측정: vnd 약 54초, alns 약 47초, vns 약 591초=10분)
때문에 비현실적이라, target_km 짧음/중간/김을 대표하는 소수 시나리오만 실행한다
(turn_cost 실제 경로 분포 검증 결과 검토 §8.4 권고 반영).

- grasp-wp-vnd, grasp-wp-alns: 짧음 2개 + 중간 2개 + 김 1개 = 5개 시나리오
- grasp-wp-vns: 1회 10분이라 짧음 1개 + 김 1개 = 2개 시나리오만
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
from src.route_engine.engines.path_utils import PathUtils, count_turns_at_or_above

# target_km 기준 짧음(circular_20=2.0, circular_13=2.2) / 중간(circular_11=3.7, circular_03=4.0) / 김(circular_04=4.8)
FULL_SAMPLE_IDS = ["circular_20", "circular_13", "circular_11", "circular_03", "circular_04"]
VNS_SAMPLE_IDS = ["circular_20", "circular_04"]  # 짧음 1개 + 김 1개만(1회 10분)

ENGINE_SAMPLES = {
    "grasp-wp-vnd": FULL_SAMPLE_IDS,
    "grasp-wp-alns": FULL_SAMPLE_IDS,
    "grasp-wp-vns": VNS_SAMPLE_IDS,
}

# 기존 5개 엔진(beam/grasp/alns/rcsp-circular, grasp-wp-local) 전수 분포와 비교하기 위한 기준값
# (turn_cost_distribution.csv 요약, 2026-09-16 1차 관측 — 참고용)
BASELINE_TURN_DEG_PER_KM = {
    "grasp-wp-local": 739.6, "beam-circular": 774.2, "alns-circular": 840.5,
    "grasp-circular": 1038.6, "rcsp-circular": 1288.0,
}


def main():
    print("그래프 로딩 중...", flush=True)
    g = _load_default_graph()
    precompute_scoring_features(g)
    utils = PathUtils(g)

    with open(REPO_ROOT / "benchmarks" / "datasets" / "route_engine.json", encoding="utf-8") as f:
        dataset = json.load(f)
    scenarios = {s["id"]: s for s in dataset["scenarios"]}

    rows = []
    t_start = time.time()
    for algo, scenario_ids in ENGINE_SAMPLES.items():
        for sid in scenario_ids:
            sc = scenarios[sid]
            start_node = utils.find_nearest_node(sc["start_lat"], sc["start_lon"])
            params = {"target_km": sc["target_km"], "profile": sc["profile"]}
            t0 = time.time()
            try:
                r = SOLVER_REGISTRY[algo].solve(g, start_node, start_node, params)
                elapsed = time.time() - t0
                path = r["paths"][0]
                closed = len(path) > 1 and path[0] == path[-1]
                metrics = utils.turn_metrics(path, closed=closed)
                angles = utils.turn_angles(path, closed=closed)
                rows.append({
                    "algorithm": algo, "scenario_id": sid, "target_km": sc["target_km"],
                    "success": True, "runtime_sec": round(elapsed, 1), "num_nodes": len(path),
                    "total_turn_deg": round(metrics.total_turn_deg, 1),
                    "max_turn_deg": round(metrics.max_turn_deg, 1),
                    "turn_deg_per_km": round(metrics.turn_deg_per_km, 2) if metrics.turn_deg_per_km else None,
                    "turn_count_ge_90": count_turns_at_or_above(angles, 90.0),
                })
                print(f"[{algo}/{sid}] 완료: {elapsed:.1f}초, turn_deg_per_km={rows[-1]['turn_deg_per_km']} "
                      f"(누적 {time.time()-t_start:.0f}초)", flush=True)
            except Exception as e:
                rows.append({
                    "algorithm": algo, "scenario_id": sid, "target_km": sc["target_km"],
                    "success": False, "runtime_sec": round(time.time() - t0, 1), "num_nodes": None,
                    "total_turn_deg": None, "max_turn_deg": None, "turn_deg_per_km": None,
                    "turn_count_ge_90": None,
                })
                print(f"[{algo}/{sid}] FAILED: {e!r}", flush=True)

    df = pd.DataFrame(rows)
    out_csv = Path(__file__).parent / "slow_engines_results.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    print("\n=== 엔진별 요약 ===", flush=True)
    ok = df[df["success"]]
    summary = ok.groupby("algorithm").agg(
        n=("total_turn_deg", "count"),
        평균실행시간초=("runtime_sec", "mean"),
        평균거리당회전량=("turn_deg_per_km", "mean"),
        평균최대회전각=("max_turn_deg", "mean"),
        평균90도이상=("turn_count_ge_90", "mean"),
    ).round(2)
    print(summary.to_string(), flush=True)

    print("\n=== 기존 5개 엔진(전수 25개) 대비 비교 ===", flush=True)
    for algo, mean_val in summary["평균거리당회전량"].items():
        rank_context = sorted(list(BASELINE_TURN_DEG_PER_KM.items()) + [(algo, mean_val)], key=lambda x: x[1])
        print(f"{algo} (거리당회전량={mean_val}) 순위 위치: {[a for a,_ in rank_context]}", flush=True)

    print(f"\n총 소요 시간: {time.time()-t_start:.0f}초, 결과 저장: {out_csv}", flush=True)


if __name__ == "__main__":
    main()
