import networkx as nx
import random

from src.route_engine.engines.path_utils import extract_coordinates


def random_walk_route(G: nx.Graph, start_node: int, target_distance_km: float = 3.0, weight: str = "length") -> dict:
    target_m = target_distance_km * 1000
    visited_edges = {}
    path_nodes = [start_node]
    total_distance = 0.0
    current = start_node

    start_x = G.nodes[start_node]["lon"]
    start_y = G.nodes[start_node]["lat"]

    while total_distance < target_m * 0.75:
        neighbors = list(G.neighbors(current))
        if not neighbors:
            break

        weights = []
        for n in neighbors:
            edge_key = tuple(sorted([current, n]))
            edge_visited = visited_edges.get(edge_key, 0)

            edge_penalty = 1.0 / (1 + edge_visited * 7)
            degree_penalty = 1.0 / (1 + max(0, 3 - G.degree(n)))

            edge_data = G.get_edge_data(current, n) or {}
            w = edge_data.get(weight, 1.0)

            progress = total_distance / target_m
            if progress < 0.7:
                nx_ = G.nodes[n]["lon"]
                ny_ = G.nodes[n]["lat"]
                dist_from_start = ((nx_ - start_x)**2 + (ny_ - start_y)**2) ** 0.5
                w = w / ((dist_from_start + 1e-6) ** 2)

            weights.append((1.0 / w) * edge_penalty * degree_penalty)

        total_w = sum(weights)
        probs = [w / total_w for w in weights]
        next_node = random.choices(neighbors, weights=probs, k=1)[0]

        edge_key = tuple(sorted([current, next_node]))
        visited_edges[edge_key] = visited_edges.get(edge_key, 0) + 1

        edge_data = G.get_edge_data(current, next_node) or {}
        total_distance += edge_data.get("length", 0)
        path_nodes.append(next_node)
        current = next_node

    if path_nodes[-1] != start_node:
        try:
            def return_weight(u, v, d):
                edge_key = tuple(sorted([u, v]))
                visit_count = visited_edges.get(edge_key, 0)
                base = d.get("length", 1.0)
                return base * (1 + visit_count * 10)

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
