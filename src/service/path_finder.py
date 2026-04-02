# src/service/path_finder.py
import networkx as nx
import random
from typing import Optional
import math


def find_nearest_node(G: nx.Graph, lat: float, lng: float) -> int:
    """위경도 → 가장 가까운 그래프 노드 ID (OSMnx 없이 직접 계산)"""
    min_dist = float("inf")
    nearest = None

    for node_id, data in G.nodes(data=True):
        node_lat = data.get("y")
        node_lng = data.get("x")
        if node_lat is None or node_lng is None:
            continue
        dist = math.sqrt((lat - node_lat) ** 2 + (lng - node_lng) ** 2)
        if dist < min_dist:
            min_dist = dist
            nearest = node_id

    return nearest


def extract_coordinates(G: nx.Graph, node_list: list) -> list:
    """노드 ID 리스트 → [[lat, lng], ...] 변환"""
    return [
        [G.nodes[n]["y"], G.nodes[n]["x"]]
        for n in node_list
        if n in G.nodes
    ]

def random_walk_route(G: nx.Graph, start_node: int, target_distance_km: float = 3.0, weight: str = "length") -> dict:
    target_m = target_distance_km * 1000
    visited_edges = {}  # (u, v): 방문 횟수
    path_nodes = [start_node]
    total_distance = 0.0
    current = start_node

    start_x = G.nodes[start_node]["x"]
    start_y = G.nodes[start_node]["y"]

    while total_distance < target_m * 0.75:  # 75%만 탐색 후 귀환
        neighbors = list(G.neighbors(current))
        if not neighbors:
            break

        # 가중치 기반 확률 선택
        weights = []
        for n in neighbors:
            edge_key = tuple(sorted([current, n]))
            visit_count = visited_edges.get(edge_key, 0)

            # 2회 이상 방문 차단, 1회는 페널티
            if visit_count >= 2:
                penalty = 0.0
            elif visit_count == 1:
                penalty = 1 / 6  # 1 / (1 + 1 * 5)
            else:
                penalty = 1.0

            edge_data = G.get_edge_data(current, n) or {}
            w = edge_data.get(weight, 1.0)

            # 출발지와 거리가 멀수록 선호 (초반에만)
            progress = total_distance / target_m
            if progress < 0.7:
                nx_ = G.nodes[n]["x"]
                ny_ = G.nodes[n]["y"]
                dist_from_start = ((nx_ - start_x)**2 + (ny_ - start_y)**2) ** 0.5
                w = w / ((dist_from_start + 1e-6) ** 2)
            
            weights.append((1.0 / w) * penalty)

        # 전부 차단된 경우 fallback: 페널티 무시하고 최소 방문 엣지로
        if all(w == 0.0 for w in weights):
            weights = []
            for n in neighbors:
                edge_key = tuple(sorted([current, n]))
                visit_count = visited_edges.get(edge_key, 0)
                edge_data = G.get_edge_data(current, n) or {}
                w = edge_data.get(weight, 1.0)
                weights.append((1.0 / w) / (1 + visit_count * 10))

        total_w = sum(weights)
        probs = [w / total_w for w in weights]
        next_node = random.choices(neighbors, weights=probs, k=1)[0]

        edge_key = tuple(sorted([current, next_node]))
        visited_edges[edge_key] = visited_edges.get(edge_key, 0) + 1

        edge_data = G.get_edge_data(current, next_node) or {}
        total_distance += edge_data.get("length", 0)
        path_nodes.append(next_node)
        current = next_node

    # 출발지 귀환
    if path_nodes[-1] != start_node:
        try:
            # 방문한 엣지에 페널티를 주는 커스텀 가중치 함수
            def return_weight(u, v, d):
                edge_key = tuple(sorted([u, v]))
                visit_count = visited_edges.get(edge_key, 0)
                base = d.get("length", 1.0)
                return base * (1 + visit_count * 10)  # 10 조정 가능

            return_path = nx.shortest_path(G, current, start_node, weight=return_weight)
            for n in return_path[1:]:
                edge_data = G.get_edge_data(path_nodes[-1], n) or {}
                total_distance += edge_data.get("length", 0)
                path_nodes.append(n)
        except nx.NetworkXNoPath:
            pass

    return {
        "nodes": path_nodes,
        "coordinates": extract_coordinates(G, path_nodes),
        "total_distance_km": round(total_distance / 1000, 2)
    }


def dijkstra_route(
    G: nx.Graph,
    start_node: int,
    end_node: int,
    weight: str = "length"
) -> dict:
    try:
        path_nodes = nx.shortest_path(G, start_node, end_node, weight=weight)
        total_distance = sum(
            (G.get_edge_data(path_nodes[i], path_nodes[i+1]) or {}).get("length", 0)
            for i in range(len(path_nodes) - 1)
        )
        return {
            "nodes": path_nodes,
            "coordinates": extract_coordinates(G, path_nodes),
            "total_distance_km": round(total_distance / 1000, 2)
        }
    except nx.NetworkXNoPath:
        print(f"경로 없음: {start_node} → {end_node}")
        return {"nodes": [], "coordinates": [], "total_distance_km": 0.0}
    except Exception as e:
        print(f"오류: {e}")
        return {"nodes": [], "coordinates": [], "total_distance_km": 0.0}


def find_route(
    G: nx.Graph,
    start_lat: float,
    start_lng: float,
    intent: dict,
    end_lat: Optional[float] = None,
    end_lng: Optional[float] = None,
) -> dict:
    start_node = find_nearest_node(G, start_lat, start_lng)
    print(f"약한 연결 요소 수: {nx.number_connected_components(G)}")
    weight = intent.get("weight", "length")
    distance_km = intent.get("distance_km", 3.0)

    if end_lat is not None and end_lng is not None:
        end_node = find_nearest_node(G, end_lat, end_lng)
        print(f"start_node: {start_node}, end_node: {end_node}")
        print(f"start in G: {start_node in G.nodes}, end in G: {end_node in G.nodes}")
        
        components = list(nx.connected_components(G))
        for i, comp in enumerate(components):
            if start_node in comp:
                print(f"start 컴포넌트: {i}, 크기: {len(comp)}")
            if end_node in comp:
                print(f"end 컴포넌트: {i}, 크기: {len(comp)}")
        result = dijkstra_route(G, start_node, end_node, weight=weight)
        result["mode"] = "dijkstra"
    else:
        result = random_walk_route(G, start_node, distance_km, weight=weight)
        result["mode"] = "random_walk"

    return result


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