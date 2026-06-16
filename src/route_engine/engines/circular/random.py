import random

import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.features import build_random_weights
from src.route_engine.scoring import apply_weights
from src.route_engine.schema import CircularRouteInput, RouteOutput


class RandomCircularRoute:
    WEIGHTS = build_random_weights()

    def __init__(self):
        pass

    def run(self, inp: CircularRouteInput, G: nx.Graph) -> RouteOutput:
        """
        출발지에서 목표 거리만큼 랜덤 워크 후 출발지로 복귀하는 순환 경로를 생성합니다.
        """
        G = apply_weights(G, self.WEIGHTS)
        target_m = (inp.target_km or 3.0) * 1000
        start_node = PathUtils.find_nearest_node(G, inp.start_lat, inp.start_lon)

        visited_edges = {}
        path_nodes = [start_node]
        total_distance = 0.0
        current = start_node
        start_x = G.nodes[start_node]["x"]
        start_y = G.nodes[start_node]["y"]

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
                w = edge_data.get("custom_score", 1.0)

                progress = total_distance / target_m
                if progress < 0.7:
                    nx_ = G.nodes[n]["x"]
                    ny_ = G.nodes[n]["y"]
                    dist_from_start = ((nx_ - start_x) ** 2 + (ny_ - start_y) ** 2) ** 0.5
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
                    ek = tuple(sorted([u, v]))
                    vc = visited_edges.get(ek, 0)
                    return d.get("length", 1.0) * (1 + vc * 10)

                return_path = nx.shortest_path(G, current, start_node, weight=return_weight)
                for n in return_path[1:]:
                    edge_data = G.get_edge_data(path_nodes[-1], n) or {}
                    total_distance += edge_data.get("length", 0)
                    path_nodes.append(n)
            except nx.NetworkXNoPath:
                pass

        return RouteOutput(
            mode="random_circular",
            coordinates=PathUtils.extract_coordinates(G, path_nodes),
        )
