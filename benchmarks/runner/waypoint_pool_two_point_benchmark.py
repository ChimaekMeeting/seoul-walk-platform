"""
benchmarks/runner/waypoint_pool_two_point_benchmark.py

WaypointPoolGenerator.build_pool_two_point() 실제 그래프 규모(노드 ~16만 / 엣지 ~22만)
실측. 이슈(#482 계열)의 To-Do "실제 그래프에서 풀 크기 실측(순환 대비 몇 배인지,
MemoryError 재현 여부)"를 확인한다.

route_engine.json의 oneway 시나리오 전체(25개, p1=start, p2=end, target_km 지정)를 쓴다.
2026-09-20 1차 실측(5개 표본, slack_m 절대값 {0,100,300})에서 "절대 m 슬랙은 여유가
빠듯한 실제 요청을 못 구하는 경우가 있다"가 나와 slack을 dist(p1,p2) 대비 비율로
바꿔 재표본했고(25개 전체, ratio {0,0.05,0.10,0.20}), 그 결과로 build_pool_two_point()
자체가 slack_ratio 파라미터(기본 5%, _DEFAULT_SLACK_RATIO)를 받아 dist(p1,p2)로
target_m을 보정하는 형태로 바뀌었다(더 이상 target_km이 짧다고 None을 반환하지 않는다).
이 스크립트는 그 바뀐 시그니처에 맞춰 slack_ratio를 그대로 전달한다.

각 시나리오에 대해:
  - dist(p1,p2)(직선 최단거리, cutoff 없는 순수 다익스트라)를 구해 "여유(target_km 대비
    직선거리 비율)"를 함께 기록한다.
  - 데이터셋의 target_km(원래 여유)과, dist(p1,p2)에 바짝 붙인 target_km(경계 근접
    케이스)을 둘 다 돌려 풀 크기가 경계 근처에서 실제로 얇아지는지 확인한다.
  - slack_ratio(_SLACK_RATIO_CASES)를 build_pool_two_point()에 그대로 전달한다.
  - 같은 p1·target_km로 build_pool()(순환)도 함께 돌려 풀 크기를 순환 대비로 비교한다.

실행: poetry run python -m benchmarks.runner.waypoint_pool_two_point_benchmark
"""

import gc
import json
import time

import pandas as pd
import networkx as nx

from benchmarks.config import (
    WALK_GRAPH_ARTIFACT,
    ROUTE_ENGINE_DATASET,
    RESULTS_DIR,
)
from src.repository.network.graph_artifact_repository import GraphArtifactRepository
from src.route_engine.engines.waypoint_pool import WaypointPoolGenerator
from src.route_engine.scoring.scoring_engine import compute_distance_only_lookup

_SLACK_RATIO_CASES = [0.0, 0.05, 0.10, 0.20]  # dist(p1,p2) 대비 비율 -> slack_m = ratio * dist_p1p2
_BOUNDARY_MARGIN = 1.02  # 경계 근접 케이스: dist(p1,p2)의 102%를 target_m으로 사용
_SCENARIO_LIMIT = None  # None이면 oneway 시나리오 전체(25개) 사용


def load_graph() -> nx.Graph:
    """waypoint_pool_benchmark.py::load_graph()와 같은 원본을 읽는다(#474 원본 통일)."""
    return GraphArtifactRepository.load(WALK_GRAPH_ARTIFACT)


def time_ms(fn):
    gc.disable()
    try:
        start = time.perf_counter()
        result = fn()
        elapsed = time.perf_counter() - start
    finally:
        gc.enable()
    return result, elapsed * 1000


def main():
    print("그래프 로딩 중...")
    G = load_graph()
    print(f"노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개 로드 완료")

    with open(ROUTE_ENGINE_DATASET, encoding="utf-8") as f:
        dataset = json.load(f)
    scenarios = [s for s in dataset["scenarios"] if s.get("mode") == "oneway"][:_SCENARIO_LIMIT]
    print(f"편도 시나리오 {len(scenarios)}개 사용")

    generator = WaypointPoolGenerator(G)
    utils = generator.utils
    weight = compute_distance_only_lookup(G)["weight"]

    rows = []
    memory_errors = []
    for case in scenarios:
        p1 = utils.find_nearest_node_with_expansion(case["start_lat"], case["start_lon"])
        p2 = utils.find_nearest_node_with_expansion(case["end_lat"], case["end_lon"])
        if p1 is None or p2 is None:
            print(f"[{case['id']}] p1/p2 노드를 찾지 못함 — 건너뜀")
            continue

        (dist_p1p2, _), dijkstra_ms = time_ms(
            lambda: (nx.single_source_dijkstra(G, p1, target=p2, weight=weight))
        )
        original_target_km = case["target_km"]
        boundary_target_km = (dist_p1p2 * _BOUNDARY_MARGIN) / 1000
        print(
            f"\n[{case['id']}] dist(p1,p2)={dist_p1p2:.1f}m "
            f"({dijkstra_ms:.1f}ms), 데이터셋 target_km={original_target_km} "
            f"(여유 {original_target_km * 1000 / dist_p1p2:.2f}배), "
            f"경계근접 target_km={boundary_target_km:.3f}"
        )

        # 비교 기준: 같은 p1·target_km로 순환 풀도 돌려본다(풀 크기 배수 비교용)
        try:
            circ_result, circ_ms = time_ms(
                lambda: generator.build_pool(case["start_lat"], case["start_lon"], original_target_km)
            )
            circ_pool_size = len(circ_result.pool_nodes) if circ_result else 0
        except MemoryError:
            memory_errors.append((case["id"], "circular", original_target_km, None))
            circ_pool_size, circ_ms = None, None

        for target_label, target_km in (
            ("dataset", original_target_km),
            ("boundary", boundary_target_km),
        ):
            for slack_ratio in _SLACK_RATIO_CASES:
                slack_m = slack_ratio * dist_p1p2  # 기록용 — 실제 계산은 함수 내부에서 함
                try:
                    result, build_ms = time_ms(
                        lambda: generator.build_pool_two_point(
                            case["start_lat"], case["start_lon"],
                            case["end_lat"], case["end_lon"],
                            target_km=target_km, slack_ratio=slack_ratio,
                        )
                    )
                except MemoryError:
                    memory_errors.append((case["id"], target_label, target_km, slack_ratio))
                    print(f"  [{target_label}] target_km={target_km:.3f}, slack_ratio={slack_ratio}: MemoryError")
                    continue

                pool_size = len(result.pool_nodes) if result is not None else None
                ratio_vs_circular = (
                    round(pool_size / circ_pool_size, 3)
                    if pool_size and circ_pool_size else None
                )
                rows.append({
                    "case_id": case["id"],
                    "dist_p1p2_m": round(dist_p1p2, 1),
                    "target_label": target_label,
                    "target_km": round(target_km, 4),
                    "slack_ratio": slack_ratio,
                    "slack_m": round(slack_m, 1),
                    "pool_size": pool_size,
                    "circular_pool_size_same_target": circ_pool_size,
                    "pool_size_ratio_vs_circular": ratio_vs_circular,
                    "build_ms": round(build_ms, 1),
                    "feasible": result is not None,
                })
                print(
                    f"  [{target_label}] target_km={target_km:.3f}, slack_ratio={slack_ratio} "
                    f"(slack_m={slack_m:.1f}): "
                    f"pool={pool_size if pool_size is not None else 'None(infeasible)'}, "
                    f"순환대비={ratio_vs_circular}, build={build_ms:.1f}ms"
                )

    result_df = pd.DataFrame(rows)
    out_dir = RESULTS_DIR / "waypoint_pool"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "waypoint_pool_two_point_benchmark.csv"
    result_df.to_csv(out_path, index=False)
    print(f"\n결과 저장 완료: {out_path}")

    if memory_errors:
        print(f"\nMemoryError 발생 {len(memory_errors)}건: {memory_errors}")
    else:
        print("\nMemoryError 재현 없음.")


if __name__ == "__main__":
    main()
