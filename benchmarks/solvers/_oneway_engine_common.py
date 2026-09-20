"""
benchmarks/solvers/_oneway_engine_common.py

astar_solver.py/dijkstra_solver.py(OnewayAstarEngine/OnewayDijkstraEngine)가 공유하는
헬퍼. 기준선은 항상 물리 거리(length) 최단경로다. 가중 비용으로 탐색한 경로도 같은
기준선과 비교해야, 안전·편안 선호에 따라 기준선 자체가 바뀌는 일을 막을 수 있다.
"""

import networkx as nx


def baseline_shortest_overlap_ratio(engine, path: list, start_node: int, end_node: int) -> float:
    """path가 물리 거리 최단경로와 겹치는 통행 거리 비율을 반환한다.

    자기 재통행은 benchmarks.results.repeated_edge_ratio가 측정한다. 이 함수는 편도
    우회가 거리 최단 기준선을 얼마나 따르는지 보는 별도 지표다.
    """
    try:
        base_path = nx.shortest_path(engine.G, start_node, end_node, weight="length")
    except nx.NetworkXNoPath:
        return 0.0

    base_edges = {frozenset((base_path[i], base_path[i + 1])) for i in range(len(base_path) - 1)}

    total_m = sum(
        (engine.G.get_edge_data(path[i], path[i + 1]) or {}).get("length", 0)
        for i in range(len(path) - 1)
    )
    if total_m <= 0:
        return 0.0

    overlap_m = sum(
        (engine.G.get_edge_data(path[i], path[i + 1]) or {}).get("length", 0)
        for i in range(len(path) - 1)
        if frozenset((path[i], path[i + 1])) in base_edges
    )
    return round(overlap_m / total_m, 4)
