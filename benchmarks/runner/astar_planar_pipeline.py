"""좌표 -> 경유지 후보 풀 -> Beam 개선 -> Dijkstra/A*(Haversine)/A*(Planar) 경로
비교 파이프라인.

waypoint_pool.py / waypoint_beam.py / landmark_planar.py를 독립 모듈 그대로
이어 붙인 수동 검증 스크립트다. route_service.py/WaypointComposerEngine 등
프로덕션에는 연결하지 않았고 engines/__init__.py에도 등록하지 않는다.

현재는 순환 경로(출발=도착)만 지원한다 — waypoint_pool.py의 r_max=target_m/2
cutoff가 라운드트립 삼각부등식 근거라 편도(출발!=도착)에는 그대로 적용되지
않는다.

세 경로(Dijkstra/A*-Haversine/A*-Planar)의 총 거리는 admissible한 휴리스틱이면
항상 동일해야 한다(cost_mismatch로 확인) — 다만 같은 비용의 경로가 여러 개
있으면(도심 격자망에서 흔함) 어느 걸 찾느냐는 탐색 순서(휴리스틱)에 따라
달라질 수 있다. 이 스크립트는 그 실제 경로 겹침 정도를 엣지 집합 Jaccard
유사도와 완전 일치 구간 수로 측정한다.

Planar 랜드마크 표는 전체 실행에서 1회만 준비하고 모든 --target-km/--repeats에서
재사용한다(2026-08-30 실측: 16개 랜드마크·16만 노드 그래프에서 약 6~7초 소요,
Haversine은 사실상 0초).
"""

import argparse
import json
from math import inf
from time import perf_counter

import networkx as nx

from src.repository.network.graph_artifact_repository import GraphArtifactRepository
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.engines.waypoint_pool import WaypointPoolGenerator
from src.route_engine.landmark_planar import select_landmarks_planar
from src.route_engine.landmark_shared import build_alt_heuristic
from src.route_engine.scoring.scoring_engine import compute_distance_only_lookup
from src.route_engine.waypoint_beam import beam_search


def _haversine_heuristic(G: nx.Graph):
    def heuristic(u, v):
        nu, nv = G.nodes[u], G.nodes[v]
        return PathUtils._haversine_m(
            nu.get("lat", 0), nu.get("lon", 0), nv.get("lat", 0), nv.get("lon", 0)
        )

    return heuristic


def _edge_set(path: list[int]) -> set[frozenset]:
    return {frozenset((path[i], path[i + 1])) for i in range(len(path) - 1)}


def _jaccard(a: set, b: set) -> float:
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def _run_query(
    *, graph, utils, weight_fn, planar_heuristic, haversine_heuristic, p1, target_km, args, parser
):
    # 1) 좌표값 -> 경유지 후보 풀 (순환: 출발=도착=p1)
    t0 = perf_counter()
    pool_gen = WaypointPoolGenerator(graph, blocked_tags=args.blocked_tags or None)
    pool = pool_gen.build_pool(args.start_lat, args.start_lon, target_km)
    if pool is None:
        parser.error("풀 생성 중 출발 좌표 근처에서 노드를 찾지 못했습니다.")
    pool_seconds = perf_counter() - t0

    ids_sorted = sorted(pool.pool_nodes, key=lambda n: (pool.dist_from_p1[n], n))
    pool_size = min(args.pool_limit, len(ids_sorted))
    if pool_size < args.waypoint_count:
        parser.error("후보 풀이 waypoint-count보다 적습니다. target-km이나 pool-limit을 조정하세요.")
    selected = (
        ids_sorted[:1]
        if pool_size == 1
        else [ids_sorted[i * (len(ids_sorted) - 1) // (pool_size - 1)] for i in range(pool_size)]
    )
    candidates = [
        dict(node_id=node, lat=graph.nodes[node]["lat"], lon=graph.nodes[node]["lon"])
        for node in selected
    ]

    def cost(a, b):
        if a == b:
            return 0.0
        if a == p1 or b == p1:
            other = b if a == p1 else a
            return pool.dist_from_p1.get(other, inf)
        d = pool.distance(a, b)
        return inf if d is None else d

    # 2) Beam으로 경유지 선택·순서 개선
    t0 = perf_counter()
    beam_result = beam_search(
        candidates=candidates,
        cost=cost,
        start_id=p1,
        end_id=p1,
        target_m=target_km * 1000,
        waypoint_count=args.waypoint_count,
        beam_width=args.beam_width,
    )
    beam_seconds = perf_counter() - t0
    if not beam_result.orders:
        parser.error("Beam에서 완성 조합을 찾지 못했습니다.")
    best = beam_result.orders[0]

    # 3) 구간(leg)마다 Dijkstra(기준) / A*(Haversine) / A*(Planar) 세 경로를 모두 복원해 비교
    stops = (p1, *best.waypoint_ids, p1)
    dijkstra_total_m = haversine_total_m = planar_total_m = 0.0
    dijkstra_seconds = haversine_seconds = planar_seconds = 0.0
    dh_jaccards: list[float] = []
    dp_jaccards: list[float] = []
    hp_jaccards: list[float] = []
    dh_exact = dp_exact = hp_exact = 0

    for a, b in zip(stops, stops[1:]):
        t0 = perf_counter()
        try:
            dijkstra_path = nx.shortest_path(graph, a, b, weight=weight_fn, method="dijkstra")
        except nx.NetworkXNoPath:
            parser.error(f"구간 {a} -> {b} 사이에 연결된 경로가 없습니다.")
        dijkstra_seconds += perf_counter() - t0

        t0 = perf_counter()
        haversine_path = nx.astar_path(graph, a, b, heuristic=haversine_heuristic, weight=weight_fn)
        haversine_seconds += perf_counter() - t0

        t0 = perf_counter()
        planar_path = nx.astar_path(graph, a, b, heuristic=planar_heuristic, weight=weight_fn)
        planar_seconds += perf_counter() - t0

        dijkstra_total_m += utils.calc_distance(dijkstra_path)
        haversine_total_m += utils.calc_distance(haversine_path)
        planar_total_m += utils.calc_distance(planar_path)

        d_edges = _edge_set(dijkstra_path)
        h_edges = _edge_set(haversine_path)
        p_edges = _edge_set(planar_path)

        dh_jaccards.append(_jaccard(d_edges, h_edges))
        dp_jaccards.append(_jaccard(d_edges, p_edges))
        hp_jaccards.append(_jaccard(h_edges, p_edges))
        dh_exact += dijkstra_path == haversine_path
        dp_exact += dijkstra_path == planar_path
        hp_exact += haversine_path == planar_path

    legs = len(stops) - 1
    cost_mismatch = (
        abs(dijkstra_total_m - best.distance_m) > 1e-6
        or abs(haversine_total_m - best.distance_m) > 1e-6
        or abs(planar_total_m - best.distance_m) > 1e-6
    )

    return dict(
        kind="query",
        target_km=target_km,
        pool_size=pool_size,
        pool_seconds=pool_seconds,
        waypoint_ids=list(best.waypoint_ids),
        beam_distance_m=best.distance_m,
        beam_error_m=best.error_m,
        beam_seconds=beam_seconds,
        legs=legs,
        dijkstra_seconds=dijkstra_seconds,
        haversine_seconds=haversine_seconds,
        planar_seconds=planar_seconds,
        dijkstra_total_m=dijkstra_total_m,
        haversine_total_m=haversine_total_m,
        planar_total_m=planar_total_m,
        cost_mismatch=cost_mismatch,
        dijkstra_vs_haversine_exact_legs=dh_exact,
        dijkstra_vs_planar_exact_legs=dp_exact,
        haversine_vs_planar_exact_legs=hp_exact,
        mean_dijkstra_vs_haversine_jaccard=sum(dh_jaccards) / legs,
        mean_dijkstra_vs_planar_jaccard=sum(dp_jaccards) / legs,
        mean_haversine_vs_planar_jaccard=sum(hp_jaccards) / legs,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", default="artifacts/walk_graph_v1.pkl")
    parser.add_argument("--data-version", default="v2-2026-08-25")
    parser.add_argument("--start-lat", type=float, required=True)
    parser.add_argument("--start-lon", type=float, required=True)
    parser.add_argument("--target-km", type=float, nargs="+", default=[3.0])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--waypoint-count", type=int, default=3)
    parser.add_argument("--beam-width", type=int, default=4)
    parser.add_argument("--pool-limit", type=int, default=60)
    parser.add_argument("--n-sectors", type=int, default=16)
    parser.add_argument("--blocked-tags", nargs="*", default=[])
    args = parser.parse_args()

    if any(km <= 0 for km in args.target_km):
        parser.error("target-km은 전부 양수여야 합니다.")
    if args.repeats < 1:
        parser.error("repeats는 1 이상이어야 합니다.")
    if args.pool_limit < max(2, args.waypoint_count):
        parser.error("pool-limit은 2 및 waypoint-count 이상이어야 합니다.")

    graph = GraphArtifactRepository.load(args.artifact, expected_data_version=args.data_version)
    if graph.is_directed() or not graph:
        parser.error("노드가 있는 무방향 그래프가 필요합니다.")
    utils = PathUtils(graph)
    weight_fn = compute_distance_only_lookup(graph, args.blocked_tags)["weight"]

    p1 = utils.find_nearest_node_with_expansion(args.start_lat, args.start_lon)
    if p1 is None:
        parser.error("출발 좌표 근처에서 노드를 찾지 못했습니다.")

    haversine_heuristic = _haversine_heuristic(graph)

    t0 = perf_counter()
    landmarks = select_landmarks_planar(graph, args.n_sectors)
    planar_heuristic, _table = build_alt_heuristic(graph, landmarks, weight="length")
    planar_setup_seconds = perf_counter() - t0

    print(json.dumps(dict(
        kind="setup",
        graph_nodes=graph.number_of_nodes(),
        graph_edges=graph.number_of_edges(),
        start_node=p1,
        n_sectors_requested=args.n_sectors,
        n_landmarks_selected=len(landmarks),
        planar_setup_seconds=planar_setup_seconds,
    )))

    for target_km in args.target_km:
        for repeat in range(args.repeats):
            result = _run_query(
                graph=graph, utils=utils, weight_fn=weight_fn,
                planar_heuristic=planar_heuristic, haversine_heuristic=haversine_heuristic,
                p1=p1, target_km=target_km, args=args, parser=parser,
            )
            result["repeat"] = repeat
            print(json.dumps(result))


if __name__ == "__main__":
    main()
