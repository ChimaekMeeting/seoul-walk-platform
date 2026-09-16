"""
turn_cost(turn_metrics) 실측 분포 확인 스크립트 — v2 (현재 활성 엔진 9종).

2026-09-16 1차 분석(turn_cost_distribution_check.py)은 legacy 순환 4종(beam/grasp/
alns/rcsp-circular)을 대상으로 했는데, 그중 3종은 같은 날짜에 이미 팀이 폐기 결정한
엔진이었다(commit 4c7c924, "되살릴 계획이 없다"). 이 스크립트는 dev 최신 상태 기준
SOLVER_REGISTRY의 실제 활성 엔진 9종(grasp-wp-*, beam-wp-*)으로 다시 측정한다.

실행: python -m analysis.turn_cost.turn_cost_distribution_v2_check (레포 루트에서)
출력: turn_cost_distribution_v2.csv (이 스크립트와 같은 디렉터리)
"""
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from benchmarks.benchmark import _load_default_graph, SOLVER_REGISTRY
from benchmarks.run_all_scenarios import CIRCULAR_ALGOS
from src.route_engine.scoring.scoring_engine import precompute_scoring_features
from src.route_engine.engines.path_utils import PathUtils, count_turns_at_or_above

SEED = 42  # benchmarks/solvers/*.py의 _DEFAULT_SEED와 동일 — 재현성 위해 명시적으로 고정
THRESHOLDS = (45.0, 60.0, 90.0)


def main():
    print("그래프 로딩 중...", flush=True)
    g = _load_default_graph()
    precompute_scoring_features(g)
    utils = PathUtils(g)

    with open(REPO_ROOT / "benchmarks" / "datasets" / "route_engine.json", encoding="utf-8") as f:
        dataset = json.load(f)
    scenarios = [s for s in dataset["scenarios"] if s["mode"] == "circular"]
    print(f"순환 시나리오 {len(scenarios)}개, 알고리즘(현재 SOLVER_REGISTRY 활성 9종) {CIRCULAR_ALGOS}", flush=True)

    rows = []
    t_start = time.time()
    for i, sc in enumerate(scenarios, 1):
        start_node = utils.find_nearest_node(sc["start_lat"], sc["start_lon"])
        target_km = sc["target_km"]
        params = {"target_km": target_km, "seed": SEED}

        ok_count = 0
        for algo in CIRCULAR_ALGOS:
            try:
                r = SOLVER_REGISTRY[algo].solve(g, start_node, start_node, params)
                path = r["paths"][0]
            except Exception as e:
                print(f"  [{sc['id']}] {algo} FAILED: {e!r}", flush=True)
                continue
            if not path:
                continue
            ok_count += 1
            closed = len(path) > 1 and path[0] == path[-1]
            metrics = utils.turn_metrics(path, closed=closed)
            angles = utils.turn_angles(path, closed=closed)
            distance_km = utils.path_distance_m(path, closed=closed) / 1000.0
            row = {
                "scenario_id": sc["id"], "algorithm": algo, "target_km": target_km,
                "distance_km": round(distance_km, 3), "num_nodes": len(path), "closed": closed,
                "total_turn_deg": round(metrics.total_turn_deg, 1),
                "max_turn_deg": round(metrics.max_turn_deg, 1),
                "turn_deg_per_km": round(metrics.turn_deg_per_km, 2) if metrics.turn_deg_per_km is not None else None,
                "candidate_turn_count": metrics.candidate_turn_count,
                "defined_turn_count": metrics.defined_turn_count,
                "undefined_turn_count": metrics.undefined_turn_count,
                "undefined_turn_reasons": json.dumps(metrics.undefined_turn_reasons, ensure_ascii=False),
            }
            for t in THRESHOLDS:
                row[f"turn_count_ge_{int(t)}"] = count_turns_at_or_above(angles, t)
            rows.append(row)

        print(f"[{i}/{len(scenarios)}] {sc['id']} 완료 (누적 {time.time()-t_start:.0f}초, "
              f"성공 {ok_count}/{len(CIRCULAR_ALGOS)})", flush=True)

    df = pd.DataFrame(rows)
    out_path = Path(__file__).parent / "turn_cost_distribution_v2.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n총 소요 시간: {time.time()-t_start:.0f}초, 결과 {len(df)}행 저장: {out_path}", flush=True)

    print("\n=== 알고리즘별 회전량 통계 ===", flush=True)
    summary = df.groupby("algorithm").agg(
        시도수=("scenario_id", "count"),
        평균총회전량=("total_turn_deg", "mean"),
        p50_총회전량=("total_turn_deg", lambda s: s.quantile(0.5)),
        p90_총회전량=("total_turn_deg", lambda s: s.quantile(0.9)),
        평균최대회전각=("max_turn_deg", "mean"),
        평균거리당회전량=("turn_deg_per_km", "mean"),
        undefined합계=("undefined_turn_count", "sum"),
        평균45도이상횟수=("turn_count_ge_45", "mean"),
        평균60도이상횟수=("turn_count_ge_60", "mean"),
        평균90도이상횟수=("turn_count_ge_90", "mean"),
    ).round(2).sort_values("평균거리당회전량")
    print(summary.to_string(), flush=True)

    total_candidate = df["candidate_turn_count"].sum()
    total_undefined = df["undefined_turn_count"].sum()
    if total_candidate:
        print(f"\n전체 candidate_turn_count 합계: {total_candidate}, undefined 합계: {total_undefined} "
              f"({100*total_undefined/total_candidate:.3f}% 정의 불가)", flush=True)


if __name__ == "__main__":
    main()
