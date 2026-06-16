import math
import random

import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.engines.oneway.dijkstra import DijkstraOnewayRoute
from src.route_engine.features import build_random_weights
from src.route_engine.scoring import apply_weights
from src.route_engine.schema import OnewayRouteInput, RouteOutput


class RandomOnewayRoute:
    WEIGHTS = build_random_weights()

    def __init__(self):
        pass

    def run(self, inp: OnewayRouteInput, G: nx.Graph) -> RouteOutput:
        """
        중간 경유지를 경유하는 우회 편도 경로를 생성합니다.
        1구간에서 사용한 엣지에 페널티를 부여해 2구간이 다른 길을 선택하도록 유도합니다.
        """
        G = apply_weights(G, self.WEIGHTS)
        start_node = PathUtils.find_nearest_node(G, inp.start_lat, inp.start_lon)
        end_node = PathUtils.find_nearest_node(G, inp.end_lat, inp.end_lon)
        target_m = (inp.target_km or 3.0) * 1000

        p1, p2 = G.nodes[start_node], G.nodes[end_node]

        candidates = []
        for node, data in G.nodes(data=True):
            if node in [start_node, end_node]:
                continue
            d1 = math.sqrt((data["x"] - p1["x"]) ** 2 + (data["y"] - p1["y"]) ** 2) * 111000
            d2 = math.sqrt((data["x"] - p2["x"]) ** 2 + (data["y"] - p2["y"]) ** 2) * 111000
            total_straight = d1 + d2
            if (target_m * 0.6) <= total_straight <= (target_m * 0.9):
                candidates.append((node, abs(total_straight - target_m * 0.8)))

        if not candidates:
            best_waypoint = PathUtils.find_nearest_node(
                G,
                (p1["y"] + p2["y"]) / 2 + 0.005,
                (p1["x"] + p2["x"]) / 2 + 0.005,
            )
        else:
            candidates.sort(key=lambda x: x[1])
            best_waypoint = random.choice(candidates[:5])[0]

        try:
            path1 = nx.shortest_path(G, start_node, best_waypoint, weight="custom_score")

            original_weights = {}
            for i in range(len(path1) - 1):
                u, v = path1[i], path1[i + 1]
                if G.has_edge(u, v):
                    original_weights[(u, v)] = G[u][v]["custom_score"]
                    G[u][v]["custom_score"] = original_weights[(u, v)] * 100

            path2 = nx.shortest_path(G, best_waypoint, end_node, weight="custom_score")

            for (u, v), old_w in original_weights.items():
                G[u][v]["custom_score"] = old_w

            full_path = path1[:-1] + path2
            return RouteOutput(
                mode="random_oneway",
                coordinates=PathUtils.extract_coordinates(G, full_path),
            )
        except Exception:
            return DijkstraOnewayRoute().run(inp, G)
