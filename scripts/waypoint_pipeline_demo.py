"""
scripts/waypoint_pipeline_demo.py

전체 파이프라인 연결 테스트: 우리 경유지 후보 풀(WaypointPoolGenerator)
-> 팀원의 경유지 선택·순서 beam_search(src/route_engine/waypoint_beam.py)
-> A*로 leg별 실제 좌표 연결.

정식 엔진이 아니라 두 팀원의 작업을 실제로 이어봤을 때 동작하는지, 그리고
overlap 비율이 얼마나 나오는지 확인하기 위한 통합 테스트/데모 스크립트.

실행: python scripts/waypoint_pipeline_demo.py
"""

import json
from collections import Counter

import networkx as nx
import pandas as pd

from benchmarks.config import ROUTE_NODES_PARQUET, ROUTE_EDGES_PARQUET, ROUTE_ENGINE_DATASET
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.engines.waypoint_pool import WaypointPoolGenerator, WaypointPoolResult
from src.route_engine.scoring.scoring_engine import compute_distance_only_lookup
from src.route_engine.waypoint_beam import beam_search

_WAYPOINT_COUNT = 3   # 논문 n=3~8 범위 중 최소값으로 우선 테스트
_BEAM_WIDTH = 8       # circular_beam.py와 동일한 폭


def load_graph() -> nx.Graph:
    nodes_df = pd.read_parquet(ROUTE_NODES_PARQUET)
    edges_df = pd.read_parquet(ROUTE_EDGES_PARQUET)
    G = nx.Graph()
    for row in nodes_df.itertuples():
        G.add_node(row.node_id, lat=row.lat, lon=row.lon)
    for row in edges_df.itertuples():
        G.add_edge(row.u, row.v, length=row.length)
    return G


def make_cost_fn(pool: WaypointPoolResult, p1: int):
    """
    beam_search()가 요구하는 CostFunction(대칭 거리, 도달 불가 시 inf) 형태로
    우리 pool.dist_from_p1/pool.distance()를 감싼다.
    """
    def cost(a: int, b: int) -> float:
        if a == b:
            return 0.0
        if a == p1:
            return pool.dist_from_p1.get(b, float("inf"))
        if b == p1:
            return pool.dist_from_p1.get(a, float("inf"))
        d = pool.distance(a, b)
        return d if d is not None else float("inf")
    return cost


def stitch_with_astar(G: nx.Graph, p1: int, waypoint_ids: tuple[int, ...]) -> list[int]:
    """p1 -> waypoint_ids[0] -> ... -> waypoint_ids[-1] -> p1 순서로 leg별 A* 연결."""
    utils = PathUtils(G)
    weight = compute_distance_only_lookup(G)["weight"]

    full_nodes = [p1]
    for target in (*waypoint_ids, p1):
        leg = utils.astar_path(full_nodes[-1], target, weight=weight)
        full_nodes += leg[1:]
    return full_nodes


def overlap_ratio(G: nx.Graph, nodes: list[int]) -> float:
    """2022년 논문 Definition 5의 f2와 동일한 방식: 중복 방문된 edge 길이 비율(%)."""
    edge_counts: Counter = Counter()
    total_length = 0.0
    for i in range(len(nodes) - 1):
        u, v = nodes[i], nodes[i + 1]
        length = (G.get_edge_data(u, v) or {}).get("length", 0.0)
        edge_counts[frozenset((u, v))] += 1
        total_length += length

    overlap_length = sum(
        (G.get_edge_data(nodes[i], nodes[i + 1]) or {}).get("length", 0.0)
        for i in range(len(nodes) - 1)
        if edge_counts[frozenset((nodes[i], nodes[i + 1]))] > 1
    )
    return 100.0 * overlap_length / total_length if total_length else 0.0


def main():
    print("그래프 로딩 중...")
    G = load_graph()
    print(f"노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개 로드 완료")

    with open(ROUTE_ENGINE_DATASET, encoding="utf-8") as f:
        dataset = json.load(f)
    case = dataset["scenarios"][0]
    target_km = 5.0
    target_m = target_km * 1000

    # 1단계: 우리 경유지 후보 풀
    generator = WaypointPoolGenerator(G)
    pool = generator.build_pool(case["start_lat"], case["start_lon"], target_km)
    if pool is None or len(pool.pool_nodes) < _WAYPOINT_COUNT:
        print("풀 생성 실패 또는 후보 부족")
        return

    utils = PathUtils(G)
    p1 = utils.find_nearest_node_with_expansion(case["start_lat"], case["start_lon"])

    # 2단계: 팀원의 beam_search — candidates/cost 형태로 우리 풀을 감싸서 그대로 전달
    candidates = [
        {"node_id": n, "lat": G.nodes[n]["lat"], "lon": G.nodes[n]["lon"]}
        for n in pool.pool_nodes
    ]
    cost = make_cost_fn(pool, p1)

    result = beam_search(
        candidates=candidates,
        cost=cost,
        start_id=p1,
        end_id=p1,
        target_m=target_m,
        waypoint_count=_WAYPOINT_COUNT,
        beam_width=_BEAM_WIDTH,
    )
    if not result.orders:
        print("beam_search가 완성 조합을 찾지 못함")
        return

    best = result.orders[0]
    print(f"beam_search 선택: {best.waypoint_ids}, 거리={best.distance_m:.1f}m, "
          f"오차={best.error_m:.1f}m, cost 호출={result.cost_calls}회")

    # 3단계: A*로 leg별 실제 좌표 연결
    full_nodes = stitch_with_astar(G, p1, best.waypoint_ids)
    total_m = utils.calc_distance(full_nodes)
    overlap = overlap_ratio(G, full_nodes)
    coords = utils.extract_coordinates(full_nodes)

    print(f"A* 연결 후 총 거리: {total_m:.1f}m (목표 {target_m:.0f}m)")
    print(f"중복 구간 비율(f2): {overlap:.1f}%")

    output = {
        "p1": {"lat": case["start_lat"], "lon": case["start_lon"]},
        "target_m": target_m,
        "r_max": pool.r_max,
        "waypoints": [
            {"node": n, "lat": G.nodes[n]["lat"], "lon": G.nodes[n]["lon"]}
            for n in best.waypoint_ids
        ],
        "route_coords": coords,
        "total_m": total_m,
        "overlap_pct": overlap,
        "beam_distance_m": best.distance_m,
        "beam_error_m": best.error_m,
    }
    out_path = "scripts/waypoint_pipeline_demo_output.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False)
    print(f"결과 저장: {out_path}")


if __name__ == "__main__":
    main()
