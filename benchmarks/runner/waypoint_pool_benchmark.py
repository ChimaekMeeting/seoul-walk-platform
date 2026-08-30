"""
benchmarks/runner/waypoint_pool_benchmark.py

WaypointPoolGenerator.build_pool() 실제 그래프 규모(노드 ~16만 / 엣지 ~22만) 벤치마크.
pairwise 거리를 lazy + 캐시로 바꾼 뒤 재측정 — 풀 생성 자체의 소요 시간과, 조합 단계를
흉내낸 무작위 distance() 조회 소요 시간을 나눠서 측정한다(더 이상 전체 쌍을 사전에
다 계산하지 않으므로 이전 버전의 MemoryError 재현 여부도 함께 확인).

실행: python -m benchmarks.runner.waypoint_pool_benchmark
"""

import json
import random
import time
import gc

import pandas as pd
import networkx as nx

from benchmarks.config import (
    ROUTE_NODES_PARQUET,
    ROUTE_EDGES_PARQUET,
    ROUTE_ENGINE_DATASET,
    RESULTS_DIR,
)
from src.route_engine.engines.waypoint_pool import WaypointPoolGenerator

_TARGET_KM_CASES = [1.0, 3.0, 5.0, 8.0]
_DISTANCE_QUERY_SAMPLE = 500  # 조합 단계 흉내 — 풀에서 무작위로 뽑은 쌍 수


def load_graph() -> nx.Graph:
    nodes_df = pd.read_parquet(ROUTE_NODES_PARQUET)
    edges_df = pd.read_parquet(ROUTE_EDGES_PARQUET)
    G = nx.Graph()
    for row in nodes_df.itertuples():
        G.add_node(row.node_id, lat=row.lat, lon=row.lon)
    for row in edges_df.itertuples():
        G.add_edge(row.u, row.v, length=row.length)
    return G


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
    scenarios = dataset["scenarios"][:5]

    generator = WaypointPoolGenerator(G)
    rows = []
    for case in scenarios:
        for target_km in _TARGET_KM_CASES:
            result, build_ms = time_ms(
                lambda: generator.build_pool(case["start_lat"], case["start_lon"], target_km)
            )
            if result is None or not result.pool_nodes:
                print(f"[{case['id']}] target_km={target_km}: 풀 생성 실패/빈 풀")
                continue

            # 조합 단계 흉내: 풀에서 무작위 쌍을 뽑아 distance()를 반복 조회
            pairs = [
                (random.choice(result.pool_nodes), random.choice(result.pool_nodes))
                for _ in range(_DISTANCE_QUERY_SAMPLE)
            ]
            _, query_ms = time_ms(lambda: [result.distance(u, v) for u, v in pairs])

            rows.append({
                "case_id": case["id"],
                "target_km": target_km,
                "r_max_m": result.r_max,
                "pool_size": len(result.pool_nodes),
                "build_ms": round(build_ms, 1),
                "query_500pairs_ms": round(query_ms, 1),
                "cached_rows": result.cached_row_count,
            })
            print(
                f"[{case['id']}] target_km={target_km}: pool={len(result.pool_nodes)}개, "
                f"build={build_ms:.1f}ms, {_DISTANCE_QUERY_SAMPLE}쌍 조회={query_ms:.1f}ms, "
                f"캐시된 행={result.cached_row_count}개"
            )

    result_df = pd.DataFrame(rows)
    out_dir = RESULTS_DIR / "waypoint_pool"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "waypoint_pool_benchmark.csv"
    result_df.to_csv(out_path, index=False)
    print(f"\n결과 저장 완료: {out_path}")


if __name__ == "__main__":
    main()
