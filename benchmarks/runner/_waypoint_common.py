"""경유지 Beam·ALNS 실행기가 공유하는 검증용 artifact·후보·거리 준비."""

import argparse
from functools import lru_cache
from math import inf, isfinite

import networkx as nx

from src.repository.network.graph_artifact_repository import GraphArtifactRepository


def argument_parser(description):
    """같은 그래프·시작점·후보 풀을 재현하기 위한 공통 실행 인자를 정의한다."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--artifact", default="artifacts/walk_graph_v1.pkl")
    parser.add_argument("--data-version", default="v2-2026-08-25")
    parser.add_argument("--start-id", type=int)
    parser.add_argument("--target-m", type=float, default=3000)
    parser.add_argument("--pool-size", type=int, default=12)
    parser.add_argument("--waypoint-count", type=int, default=3)
    parser.add_argument("--beam-width", type=int, default=2)
    return parser


def prepare_fixture(args, parser):
    """순환 검증용 작은 후보 풀과 대칭 최단거리 함수를 준비한다.

    팀원 후보 생성 모듈의 구현이 아니다. 두 실행기의 검증 조건을 맞추는 용도다.
    """
    if not isfinite(args.target_m) or args.target_m <= 0:
        parser.error("target-m은 유한한 양수여야 합니다.")
    if args.pool_size < max(2, args.waypoint_count) or args.waypoint_count < 1:
        parser.error("pool-size는 2 및 waypoint-count 이상이어야 합니다.")
    if args.beam_width < 1:
        parser.error("beam-width는 1 이상이어야 합니다.")
    graph = GraphArtifactRepository.load(
        args.artifact, expected_data_version=args.data_version
    )
    if graph.is_directed() or not graph:
        parser.error("노드가 있는 무방향 그래프가 필요합니다.")
    start = args.start_id
    if start is None:
        start = min(max(nx.connected_components(graph), key=len))
    if start not in graph:
        parser.error("start-id가 그래프에 없습니다.")
    reachable = nx.single_source_dijkstra_path_length(
        graph, start, cutoff=args.target_m / 2, weight="length"
    )
    ids = sorted(
        (node for node in reachable if node != start),
        key=lambda node: (reachable[node], node),
    )
    if len(ids) < args.pool_size:
        parser.error("cutoff 안의 후보가 부족합니다. 시작점이나 pool-size를 바꾸세요.")
    selected = [
        ids[i * (len(ids) - 1) // (args.pool_size - 1)] for i in range(args.pool_size)
    ]
    pool = [
        dict(node_id=node, lat=graph.nodes[node]["lat"], lon=graph.nodes[node]["lon"])
        for node in selected
    ]

    @lru_cache(maxsize=1024)
    def cached_distance(a, b):
        """정렬된 노드 쌍의 실제 최단거리를 계산하고 최대 1024쌍을 캐시한다."""
        try:
            return nx.shortest_path_length(graph, a, b, weight="length")
        except nx.NetworkXNoPath:
            return inf

    def cost(a, b):
        """무방향 그래프의 역방향 호출도 같은 캐시 항목을 사용한다."""
        return cached_distance(min(a, b), max(a, b))

    return graph, start, pool, cost, cached_distance
