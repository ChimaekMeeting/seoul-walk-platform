import networkx as nx
from typing import Any


def filter_graph_by_request(graph: nx.Graph, request: dict[str, Any]) -> nx.Graph:
    """
    요청 조건에 맞게 graph의 node/edge를 필터링합니다.
    원본 그래프를 보호하기 위해 copy본에 적용하여 반환합니다.

    Args:
        graph  : load_route_graph()로 로드된 nx.Graph
        request: {
            "exclude_underground" : bool       지하 노드 제외 여부 (기본값 False)
            "exclude_overpass"    : bool       고가 노드 제외 여부 (기본값 False)
            "blocked_node_types"  : list[str]  제외할 node_type 목록 (예: ["highway"])
        }

    Returns:
        nx.Graph: 필터링된 그래프 (copy본)

    금지:
        feature 점수 계산, custom_score 계산, route algorithm 호출 금지
    """
    G = graph.copy()

    exclude_underground = request.get("exclude_underground", False)
    exclude_overpass    = request.get("exclude_overpass", False)
    # VAL-COORD-006 ①: profiles의 blocked_tags=["highway"] 등 node_type 기반 제외
    blocked_node_types  = set(request.get("blocked_node_types", []))

    nodes_to_remove = [
        node_id
        for node_id, data in G.nodes(data=True)
        if (exclude_underground and data.get("is_underground"))
        or (exclude_overpass and data.get("is_overpass"))
        or (blocked_node_types and data.get("node_type") in blocked_node_types)
    ]

    G.remove_nodes_from(nodes_to_remove)

    return G
