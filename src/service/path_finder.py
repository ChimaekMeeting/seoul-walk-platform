# src/service/path_finder.py
import networkx as nx
import random
from typing import Optional
import math


def find_nearest_node(G: nx.DiGraph, lat: float, lng: float) -> int:
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


def extract_coordinates(G: nx.DiGraph, node_list: list) -> list:
    """노드 ID 리스트 → [[lat, lng], ...] 변환"""
    return [
        [G.nodes[n]["y"], G.nodes[n]["x"]]
        for n in node_list
        if n in G.nodes
    ]


def random_walk_route(
    G: nx.DiGraph,
    start_node: int,
    target_distance_km: float = 3.0,
    weight: str = "length"
) -> dict:
    target_m = target_distance_km * 1000
    visited = set([start_node])
    path_nodes = [start_node]
    total_distance = 0.0
    current = start_node

    while total_distance < target_m:
        neighbors = list(G.neighbors(current))
        if not neighbors:
            break

        unvisited = [n for n in neighbors if n not in visited]
        candidates = unvisited if unvisited else neighbors

        weights = []
        for n in candidates:
            edge_data = G.get_edge_data(current, n) or {}
            w = edge_data.get(weight, 1.0)
            weights.append(1.0 / (float(w) + 1e-6))

        total_w = sum(weights)
        probs = [w / total_w for w in weights]
        next_node = random.choices(candidates, weights=probs, k=1)[0]

        edge_data = G.get_edge_data(current, next_node) or {}
        total_distance += edge_data.get("length", 0)
        path_nodes.append(next_node)
        visited.add(next_node)
        current = next_node

    # 출발지 귀환
    if path_nodes[-1] != start_node:
        try:
            return_path = nx.shortest_path(G, current, start_node, weight="length")
            for n in return_path[1:]:
                edge_data = G.get_edge_data(path_nodes[-2], n) or {}
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
    G: nx.DiGraph,
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
    G: nx.DiGraph,
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