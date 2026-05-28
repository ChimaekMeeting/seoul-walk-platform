import networkx as nx
from typing import Optional
import math

def find_nearest_node(G: nx.Graph, lat: float, lon: float) -> int:
    """위경도 → 가장 가까운 그래프 노드 ID (OSMnx 없이 직접 계산)"""
    min_dist = float("inf")
    nearest = None

    for node_id, data in G.nodes(data=True):
        node_lat = data.get("y")
        node_lon = data.get("x")
        if node_lat is None or node_lon is None:
            continue
        dist = math.sqrt((lat - node_lat) ** 2 + (lon - node_lon) ** 2)
        if dist < min_dist:
            min_dist = dist
            nearest = node_id

    return nearest

def extract_coordinates(G: nx.Graph, node_list: list) -> list:
    """노드 ID 리스트 → [[lat, lon], ...] 변환"""
    return [
        [G.nodes[n]["y"], G.nodes[n]["x"]]
        for n in node_list
        if n in G.nodes
    ]

def prune_dead_ends(path_nodes: list, G: nx.Graph, max_branch_length: float = 400.0) -> list:
    """
    왕복 가지치기: 같은 노드가 두 번 등장하는 구간 중
    짧은 것(max_branch_length 미만)을 제거
    """
    pruned = list(path_nodes)
    changed = True

    while changed:
        changed = False
        node_positions = {}
        candidates = []  # (length, first, last) 후보 전체 수집

        for i, node in enumerate(pruned):
            if node in node_positions:
                first = node_positions[node]
                branch_length = sum(
                    (G.get_edge_data(pruned[j], pruned[j+1]) or {}).get("length", 0)
                    for j in range(first, i)
                )
                if branch_length < max_branch_length:
                    candidates.append((branch_length, first, i))
            else:
                node_positions[node] = i

        if candidates:
            # 가장 짧은 것부터 제거
            _, first, last = min(candidates, key=lambda x: x[0])
            pruned = pruned[:first + 1] + pruned[last + 1:]
            changed = True

    return pruned

def remove_dead_ends(G: nx.Graph) -> nx.Graph:
    G = G.copy()
    while True:
        dead_ends = [n for n, d in G.degree() if d == 1]
        if not dead_ends:
            break
        G.remove_nodes_from(dead_ends)
    return G