import math
import random

import networkx as nx

from src.route_engine.engines.path_utils import extract_coordinates, prune_dead_ends

FLAT_THRESHOLD = 0.7


def _flat_edge_weight(u: int, v: int, data: dict) -> float:
    length = data.get("length", 1.0) or 1.0
    slope  = data.get("slope_score", 0.5) or 0.5
    return length * (2.0 - slope) ** 2


def _angle_to(G: nx.Graph, a: int, b: int) -> float:
    dx = G.nodes[b].get("lon", 0) - G.nodes[a].get("lon", 0)
    dy = G.nodes[b].get("lat", 0) - G.nodes[a].get("lat", 0)
    return math.degrees(math.atan2(dx, dy)) % 360


def _angle_diff(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return d if d <= 180 else 360 - d


def flat_circular_route(
    G: nx.Graph,
    start_node: int,
    target_distance_km: float = 3.0,
) -> dict:
    """
    출발지 → 평지 진입 → 평지 순환 → 출발지 복귀.

    Phase 1. 접근  : 출발지 → 가장 가까운 평지 노드 최단경로
    Phase 2. 순환  : 방향 유지 + 급경사 회피 원형 탐색
    Phase 3. 복귀  : 출발지까지 평지 우선 최단경로
    """
    target_m   = target_distance_km * 1000
    path_nodes = [start_node]
    total_dist = 0.0
    sx = G.nodes[start_node].get("lon", 0)
    sy = G.nodes[start_node].get("lat", 0)

    # Phase 1: 평지 진입점 탐색
    flat_nodes = {
        n
        for u, v, d in G.edges(data=True)
        if (d.get("slope_score") or 0) >= FLAT_THRESHOLD
        for n in (u, v)
    }

    flat_entry = start_node
    if start_node not in flat_nodes and flat_nodes:
        min_dist = float("inf")
        for node in flat_nodes:
            nd = G.nodes[node]
            if "lon" not in nd or "lat" not in nd:
                continue
            d = math.sqrt((nd["lon"] - sx) ** 2 + (nd["lat"] - sy) ** 2) * 111000
            if d < min_dist and d < target_m * 2:
                min_dist = d
                flat_entry = node

    if flat_entry != start_node:
        try:
            approach = nx.shortest_path(G, start_node, flat_entry, weight="length")
            for n in approach[1:]:
                total_dist += (G.get_edge_data(path_nodes[-1], n) or {}).get("length", 0)
                path_nodes.append(n)
        except nx.NetworkXNoPath:
            flat_entry = start_node

    # Phase 2: 평지 순환
    approach_dist = total_dist
    loop_target   = max(target_m - approach_dist * 2, target_m * 0.5)
    current       = flat_entry
    visited_edges: dict = {}
    loop_dist     = 0.0
    heading       = random.uniform(0, 360)

    while loop_dist < loop_target:
        neighbors = list(G.neighbors(current))
        if not neighbors:
            break

        probs = []
        for n in neighbors:
            edge_key  = tuple(sorted([current, n]))
            edge_data = G.get_edge_data(current, n) or {}
            slope     = edge_data.get("slope_score", 0.5) or 0.5
            slope_w   = slope if slope >= FLAT_THRESHOLD else 0.01
            ang       = _angle_to(G, current, n)
            dir_score = max(0.01, 1.0 - _angle_diff(ang, heading) / 180.0)
            visit_pen = 1.0 / (1 + visited_edges.get(edge_key, 0) * 6)
            probs.append(slope_w * dir_score * visit_pen)

        total_p = sum(probs)
        if total_p == 0:
            break
        probs = [p / total_p for p in probs]

        next_node = random.choices(neighbors, weights=probs, k=1)[0]
        edge_key  = tuple(sorted([current, next_node]))
        visited_edges[edge_key] = visited_edges.get(edge_key, 0) + 1

        step        = (G.get_edge_data(current, next_node) or {}).get("length", 0)
        loop_dist  += step
        total_dist += step
        path_nodes.append(next_node)
        current = next_node

        cur_ang    = _angle_to(G, flat_entry, current)
        target_ang = (cur_ang + 90) % 360
        heading    = (heading * 0.85 + target_ang * 0.15) % 360

    # Phase 3: 복귀
    if path_nodes[-1] != start_node:
        try:
            def return_weight(u, v, d):
                ek = tuple(sorted([u, v]))
                return _flat_edge_weight(u, v, d) * (1 + visited_edges.get(ek, 0) * 2)

            return_path = nx.shortest_path(G, current, start_node, weight=return_weight)
            for n in return_path[1:]:
                total_dist += (G.get_edge_data(path_nodes[-1], n) or {}).get("length", 0)
                path_nodes.append(n)
        except nx.NetworkXNoPath:
            pass

    path_nodes  = prune_dead_ends(path_nodes, G)
    slope_scores = [
        (G.get_edge_data(path_nodes[i], path_nodes[i + 1]) or {}).get("slope_score", 0.5) or 0.5
        for i in range(len(path_nodes) - 1)
    ]
    avg_slope = round(sum(slope_scores) / len(slope_scores), 4) if slope_scores else 0.0

    return {
        "nodes":              path_nodes,
        "coordinates":        extract_coordinates(G, path_nodes),
        "total_distance_km":  round(total_dist / 1000, 2),
        "avg_slope_score":    avg_slope,
        "flat_entry_node":    flat_entry,
    }
