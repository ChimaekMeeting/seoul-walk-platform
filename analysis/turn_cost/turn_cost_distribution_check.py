"""
turn_cost(turn_metrics) 실측 분포 확인 스크립트 — 현재 활성 순환 엔진 9종
(grasp-wp-local/vnd/vns/alns, beam-wp, beam-wp-local/vnd/vns/alns) 대상.

임계값(30/45/60/75/90/120도) 민감도 분석을 위해 회전각 원본 리스트를
angles_deg_json 컬럼에 함께 저장한다 — 나중에 다른 임계값 후보가 필요해도
엔진을 다시 돌리지 않고 이 CSV만 다시 읽으면 된다.

실행: python analysis/turn_cost/turn_cost_distribution_check.py (레포 루트에서)
출력: turn_cost_distribution.csv (이 스크립트와 같은 디렉터리)
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
THRESHOLDS = (30.0, 45.0, 60.0, 75.0, 90.0, 120.0)  # 임계값 민감도 분석용 후보(잠정)


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
                "angles_deg_json": json.dumps([round(a, 2) for a in angles]),
            }
            for t in THRESHOLDS:
                row[f"turn_count_ge_{int(t)}"] = count_turns_at_or_above(angles, t)
            rows.append(row)

        print(f"[{i}/{len(scenarios)}] {sc['id']} 완료 (누적 {time.time()-t_start:.0f}초, "
              f"성공 {ok_count}/{len(CIRCULAR_ALGOS)})", flush=True)

    df = pd.DataFrame(rows)
    out_path = Path(__file__).parent / "turn_cost_distribution.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n총 소요 시간: {time.time()-t_start:.0f}초, 결과 {len(df)}행 저장: {out_path}", flush=True)

    print("\n=== 알고리즘별 회전량 통계 ===", flush=True)
    agg_kwargs = dict(
        시도수=("scenario_id", "count"),
        평균총회전량=("total_turn_deg", "mean"),
        p50_총회전량=("total_turn_deg", lambda s: s.quantile(0.5)),
        p90_총회전량=("total_turn_deg", lambda s: s.quantile(0.9)),
        평균최대회전각=("max_turn_deg", "mean"),
        평균거리당회전량=("turn_deg_per_km", "mean"),
        undefined합계=("undefined_turn_count", "sum"),
    )
    for t in THRESHOLDS:
        agg_kwargs[f"평균{int(t)}도이상횟수"] = (f"turn_count_ge_{int(t)}", "mean")
    summary = df.groupby("algorithm").agg(**agg_kwargs).round(2).sort_values("평균거리당회전량")
    print(summary.to_string(), flush=True)

    total_candidate = df["candidate_turn_count"].sum()
    total_undefined = df["undefined_turn_count"].sum()
    if total_candidate:
        print(f"\n전체 candidate_turn_count 합계: {total_candidate}, undefined 합계: {total_undefined} "
              f"({100*total_undefined/total_candidate:.3f}% 정의 불가)", flush=True)


if __name__ == "__main__":
    main()
