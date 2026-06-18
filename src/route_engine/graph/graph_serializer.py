import networkx as nx
from typing import Any


def graph_path_to_coordinates(graph: nx.Graph, path: list[Any]) -> list[list[float]]:
    """
    graph와 path node 리스트를 좌표 리스트([[lat, lon], ...])로 변환합니다.

    Args:
        graph : route_engine 표준 그래프 (node 속성에 lat, lon 포함)
        path  : node id 리스트 (경로 탐색 결과)

    Returns:
        [[lat, lon], ...] 형태의 좌표 리스트

    금지:
        자연어 설명 생성, UI event 생성, route algorithm 호출 금지
    """
    coordinates = []

    for node_id in path:
        data = graph.nodes.get(node_id, {})
        lat = data.get("lat")
        lon = data.get("lon")

        if lat is None or lon is None:
            continue

        coordinates.append([lat, lon])

    return coordinates
