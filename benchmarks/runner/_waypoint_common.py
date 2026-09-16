"""경유지 Beam·ALNS 실행기가 공유하는 검증용 artifact·후보·거리 준비."""

import argparse
from functools import lru_cache
from math import inf, isfinite

import networkx as nx

from src.repository.network.graph_artifact_repository import GraphArtifactRepository
from src.route_engine.waypoint_evaluation import RouteEvaluator, WaypointObjective


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
    parser.add_argument(
        "--tolerances",
        type=float,
        nargs="+",
        help="거리 전용 실행과 비교할 허용 비율. 예: 0.025 0.05 0.075",
    )
    parser.add_argument("--path-cache-size", type=int, default=1024)
    return parser


def evaluation_modes(args, parser):
    """거리 전용과 명시한 허용 오차들을 비교 목록으로 반환한다."""
    if args.path_cache_size < 0:
        parser.error("path-cache-size는 0 이상이어야 합니다.")
    tolerances = args.tolerances or []
    try:
        for value in tolerances:
            WaypointObjective(args.target_m, value)
    except ValueError as error:
        parser.error(str(error))
    return [None, *dict.fromkeys(tolerances)]


def prepare_route_evaluator(graph, cache_size):
    """동일한 artifact 그래프의 최단 도로 경로와 엣지 길이를 공급한다."""
    if graph.is_multigraph():
        raise ValueError(
            "현재 도로 식별은 단순 그래프용입니다. 다중 엣지는 별도 키가 필요합니다."
        )

    def path(a, b):
        """두 노드 사이의 length 최단경로를 반환하고 단절은 None으로 알린다."""
        try:
            return nx.shortest_path(graph, a, b, weight="length")
        except nx.NetworkXNoPath:
            return None

    def edge_length(a, b):
        """누락된 엣지·길이를 숨기지 않고 실제 도로 길이를 제공한다."""
        return graph[a][b]["length"]

    return RouteEvaluator(path, edge_length, cache_size=cache_size)


def quality_fields(order, target_m, tolerance):
    """결과의 거리·재통행과 해당 비교 설정에서의 허용 범위 충족을 기록한다."""
    metrics = order.route_metrics
    return dict(
        mode="distance_only" if tolerance is None else "overlap_aware",
        tolerance_ratio=tolerance,
        within_tolerance=(
            None
            if tolerance is None
            else WaypointObjective(target_m, tolerance).within_tolerance(order)
        ),
        error_ratio=order.error_m / target_m,
        repeated_m=metrics.repeated_m,
        overlap_ratio=metrics.overlap_ratio,
    )


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
