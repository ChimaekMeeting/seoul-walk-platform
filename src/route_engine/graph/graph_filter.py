import networkx as nx
from typing import Any


def filter_graph_by_request(graph: nx.Graph, request: dict[str, Any]) -> nx.Graph:
    """
    요청 조건에 맞게 graph의 node/edge를 필터링합니다.
    원본 그래프를 보호하기 위해 copy본에 적용하여 반환합니다.

    Args:
        graph  : load_route_graph()로 로드된 nx.Graph
        request: {
            "exclude_underground" : bool  지하 노드 제외 여부 (기본값 False)
            "exclude_overpass"    : bool  고가 노드 제외 여부 (기본값 False)
        }

    Returns:
        nx.Graph: 필터링된 그래프 (copy본)

    금지:
        feature 점수 계산, custom_score 계산, route algorithm 호출 금지
    """
    G = graph.copy()

    exclude_underground = request.get("exclude_underground", False)
    exclude_overpass = request.get("exclude_overpass", False)

    nodes_to_remove = [
        node_id
        for node_id, data in G.nodes(data=True)
        if (exclude_underground and data.get("is_underground"))
        or (exclude_overpass and data.get("is_overpass"))
    ]

    G.remove_nodes_from(nodes_to_remove)

    return G
