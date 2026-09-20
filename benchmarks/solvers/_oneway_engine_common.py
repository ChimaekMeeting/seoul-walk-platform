"""
benchmarks/solvers/_oneway_engine_common.py

astar_solver.py/dijkstra_solver.py(OnewayAstarEngine/OnewayDijkstraEngine)가 공유하는
헬퍼. 기준선은 항상 물리 거리(length) 최단경로다. 가중 비용으로 탐색한 경로도 같은
기준선과 비교해야, 안전·편안 선호에 따라 기준선 자체가 바뀌는 일을 막을 수 있다.
"""

import networkx as nx


def baseline_shortest_metrics(engine, path: list, start_node: int, end_node: int) -> tuple[float, float] | None:
    """물리 최단 기준선의 길이(km)와 path의 기준선 중첩 비율을 함께 계산한다.

    자기 재통행은 benchmarks.results.repeated_edge_ratio가 측정한다. 이 함수는 편도
    우회가 거리 최단 기준선을 얼마나 따르는지 보는 별도 지표다. 기준선 탐색을 한 번만
    수행해 baseline_shortest_km와 baseline_shortest_overlap_ratio가 같은 경로를 기준으로
    하도록 묶는다.
    """
    try:
        base_path = nx.shortest_path(engine.G, start_node, end_node, weight="length")
    except nx.NetworkXNoPath:
        return None

    baseline_m = sum(
        (engine.G.get_edge_data(base_path[i], base_path[i + 1]) or {}).get("length", 0)
        for i in range(len(base_path) - 1)
    )

    base_edges = {frozenset((base_path[i], base_path[i + 1])) for i in range(len(base_path) - 1)}

    total_m = sum(
        (engine.G.get_edge_data(path[i], path[i + 1]) or {}).get("length", 0)
        for i in range(len(path) - 1)
    )
    if total_m <= 0:
        return None

    overlap_m = sum(
        (engine.G.get_edge_data(path[i], path[i + 1]) or {}).get("length", 0)
        for i in range(len(path) - 1)
        if frozenset((path[i], path[i + 1])) in base_edges
    )
    return round(baseline_m / 1000, 4), round(overlap_m / total_m, 4)


def baseline_shortest_overlap_ratio(engine, path: list, start_node: int, end_node: int) -> float | None:
    """기존 단일 중첩 지표 호출부용 얇은 호환 래퍼."""
    metrics = baseline_shortest_metrics(engine, path, start_node, end_node)
    return metrics[1] if metrics is not None else None
