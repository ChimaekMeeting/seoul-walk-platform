"""
benchmarks/solvers/_oneway_engine_common.py

astar_solver.py/dijkstra_solver.py(OnewayAstarEngine/OnewayDijkstraEngine)가 공유하는
헬퍼. 두 엔진 다 engine._weight_fn을 노출하므로 base_shortest_path_overlap_ratio()가
이를 이용해 베이스 최단경로와의 겹침을 측정한다.
"""

import networkx as nx


def base_shortest_path_overlap_ratio(engine, pruned_path: list, start_node: int, end_node: int) -> float:
    """pruned_path가 베이스 최단경로(engine._weight_fn 기준)와 겹치는 구간의 거리 비율을 반환한다.

    (benchmark.py의 edge_overlap_ratio는 '자기 자신과의 왕복 중복'이라 다른 지표임).
    """
    try:
        weight = getattr(engine, "_weight_fn", None) or "length"
        base_path = nx.shortest_path(engine.G, start_node, end_node, weight=weight)
    except nx.NetworkXNoPath:
        return 0.0

    base_edges = {frozenset((base_path[i], base_path[i + 1])) for i in range(len(base_path) - 1)}

    total_m = sum(
        (engine.G.get_edge_data(pruned_path[i], pruned_path[i + 1]) or {}).get("length", 0)
        for i in range(len(pruned_path) - 1)
    )
    if total_m <= 0:
        return 0.0

    overlap_m = sum(
        (engine.G.get_edge_data(pruned_path[i], pruned_path[i + 1]) or {}).get("length", 0)
        for i in range(len(pruned_path) - 1)
        if frozenset((pruned_path[i], pruned_path[i + 1])) in base_edges
    )
    return round(overlap_m / total_m, 4)
