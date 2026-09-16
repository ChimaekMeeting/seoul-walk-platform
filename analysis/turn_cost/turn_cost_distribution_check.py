"""
turn_cost(turn_metrics) 실측 분포 확인 스크립트.

목적: 새로 추가한 PathUtils.turn_metrics를 실제 서울 도보 그래프 + 기존 벤치마크
순환 시나리오(benchmarks/datasets/route_engine.json)의 실제 생성 경로에 적용해,
회전량 분포(총회전량/최대회전각/거리당 회전량)와 정의 불가 회전 비율을 확인한다.

범위: grasp-wp-vnd/vns/alns는 1회 호출에 100초 이상 걸려(사전 확인) 25개 시나리오
전수 실행이 비현실적이라 이번 배치에서 제외한다(별도 후속 작업으로 남김).
beam-circular는 benchmarks/solvers/_circular_engine_common.py::run_circular_engine이
CircularBeamEngine.find_path()의 반환 타입(list[list[int]], 후보 3개)을 그대로
prune_dead_ends에 넘기는 기존 버그가 있어(이번 작업과 무관, 별도 보고 대상) 그
어댑터를 우회하고 engine.find_path()[0](대표 후보)을 직접 사용한다.

실행: python turn_cost_distribution_check.py (레포 루트에서, PYTHONPATH에 레포 루트 필요)
출력: turn_cost_distribution.csv (이 스크립트와 같은 디렉터리)
"""
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]  # analysis/turn_cost/ 기준 레포 루트
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from benchmarks.benchmark import _load_default_graph, SOLVER_REGISTRY
from src.route_engine.scoring.scoring_engine import precompute_scoring_features, calculate_custom_score
from src.route_engine.engines.path_utils import PathUtils, count_turns_at_or_above
from src.route_engine.engines.circular_beam import CircularBeamEngine
from src.schema.route_schema import CircularRouteInput

FAST_ALGOS = ["grasp-circular", "alns-circular", "rcsp-circular"]
SLOW_ALGOS = ["grasp-wp-local"]  # grasp-wp-vnd/vns/alns는 시간 예산상 제외(개별 확인 필요)
THRESHOLDS = (45.0, 60.0, 90.0)


def get_beam_path(g, engine_utils, start_node, target_km, profile):
    """run_circular_engine의 기존 list[list[int]] 처리 버그를 우회해 대표 후보(0번)만 사용."""
    inp = CircularRouteInput(start_lat=0.0, start_lon=0.0, target_km=target_km)
    engine = CircularBeamEngine(inp=inp, G=g, custom_weights=None, profile=profile)
    calculate_custom_score(engine.G, {
        "mode": engine.scoring_mode, "weights": engine.weights, "blocked_tags": engine.blocked_tags,
    })
    candidates = engine.find_path(start_node, target_km)
    nodes = candidates[0]
    return engine.utils.prune_dead_ends(nodes)


def main():
    print("그래프 로딩 중...", flush=True)
    g = _load_default_graph()
    precompute_scoring_features(g)
    utils = PathUtils(g)

    with open(REPO_ROOT / "benchmarks" / "datasets" / "route_engine.json", encoding="utf-8") as f:
        dataset = json.load(f)
    scenarios = [s for s in dataset["scenarios"] if s["mode"] == "circular"]
    print(f"순환 시나리오 {len(scenarios)}개, 알고리즘 {['beam-circular'] + FAST_ALGOS + SLOW_ALGOS}", flush=True)

    rows = []
    t_start = time.time()
    for i, sc in enumerate(scenarios, 1):
        start_node = utils.find_nearest_node(sc["start_lat"], sc["start_lon"])
        target_km, profile = sc["target_km"], sc["profile"]
        params = {"target_km": target_km, "profile": profile}

        algo_paths = {}
        try:
            algo_paths["beam-circular"] = get_beam_path(g, utils, start_node, target_km, profile)
        except Exception as e:
            print(f"  [{sc['id']}] beam-circular FAILED: {e!r}", flush=True)

        for key in FAST_ALGOS + SLOW_ALGOS:
            try:
                r = SOLVER_REGISTRY[key].solve(g, start_node, start_node, params)
                algo_paths[key] = r["paths"][0]
            except Exception as e:
                print(f"  [{sc['id']}] {key} FAILED: {e!r}", flush=True)

        for algo, path in algo_paths.items():
            if not path:
                continue
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
              f"성공 {len(algo_paths)}/{1+len(FAST_ALGOS)+len(SLOW_ALGOS)})", flush=True)

    df = pd.DataFrame(rows)
    out_path = Path(__file__).parent / "turn_cost_distribution.csv"
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
        평균undefined비율=("undefined_turn_count", lambda s: (s.sum())),
        평균45도이상횟수=("turn_count_ge_45", "mean"),
        평균60도이상횟수=("turn_count_ge_60", "mean"),
        평균90도이상횟수=("turn_count_ge_90", "mean"),
    ).round(2)
    print(summary.to_string(), flush=True)

    total_candidate = df["candidate_turn_count"].sum()
    total_undefined = df["undefined_turn_count"].sum()
    print(f"\n전체 candidate_turn_count 합계: {total_candidate}, undefined 합계: {total_undefined} "
          f"({100*total_undefined/total_candidate:.3f}% 정의 불가)" if total_candidate else "", flush=True)


if __name__ == "__main__":
    main()
