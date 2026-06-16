import math
import random

import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.features import build_flat_weights
from src.route_engine.schema import CircularRouteInput, RouteOutput

FLAT_THRESHOLD = 0.7


class FlatCircularRoute:
    WEIGHTS = build_flat_weights()

    def __init__(self):
        pass

    def run(self, inp: CircularRouteInput, G: nx.Graph) -> RouteOutput:
        """
        경사가 낮은 구간을 우선 탐색하여 평지 중심의 순환 경로를 생성합니다.
        """
        target_m = (inp.target_km or 3.0) * 1000
        start_node = PathUtils.find_nearest_node(G, inp.start_lat, inp.start_lon)
        path_nodes = [start_node]
        total_dist = 0.0
        sx = G.nodes[start_node].get("x", 0)
        sy = G.nodes[start_node].get("y", 0)

        flat_nodes = set()
        for u, v, d in G.edges(data=True):
            if (d.get("slope_score") or 0) >= FLAT_THRESHOLD:
                flat_nodes.add(u)
                flat_nodes.add(v)

        flat_entry = start_node
        if start_node not in flat_nodes and flat_nodes:
            min_dist = float("inf")
            for node in flat_nodes:
                nd = G.nodes[node]
                if "x" not in nd or "y" not in nd:
                    continue
                d = math.sqrt((nd["x"] - sx) ** 2 + (nd["y"] - sy) ** 2) * 111000
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

        approach_dist = total_dist
        loop_target = max(target_m - approach_dist * 2, target_m * 0.5)
        current = flat_entry
        visited_edges = {}
        loop_dist = 0.0
        heading = random.uniform(0, 360)

        while loop_dist < loop_target:
            neighbors = list(G.neighbors(current))
            if not neighbors:
                break

            probs = []
            for n in neighbors:
                edge_key = tuple(sorted([current, n]))
                edge_data = G.get_edge_data(current, n) or {}
                slope = edge_data.get("slope_score", 0.5) or 0.5
                visit_cnt = visited_edges.get(edge_key, 0)

                slope_w = slope if slope >= FLAT_THRESHOLD else 0.01
                ang = self._angle_to(G, current, n)
                dir_score = max(0.01, 1.0 - self._angle_diff(ang, heading) / 180.0)
                visit_pen = 1.0 / (1 + visit_cnt * 6)
                probs.append(slope_w * dir_score * visit_pen)

            total_p = sum(probs)
            if total_p == 0:
                break
            probs = [p / total_p for p in probs]

            next_node = random.choices(neighbors, weights=probs, k=1)[0]
            edge_key = tuple(sorted([current, next_node]))
            visited_edges[edge_key] = visited_edges.get(edge_key, 0) + 1

            step = (G.get_edge_data(current, next_node) or {}).get("length", 0)
            loop_dist += step
            total_dist += step
            path_nodes.append(next_node)
            current = next_node

            cur_ang = self._angle_to(G, flat_entry, current)
            target_ang = (cur_ang + 90) % 360
            heading = (heading * 0.85 + target_ang * 0.15) % 360

        if path_nodes[-1] != start_node:
            try:
                def return_weight(u, v, d):
                    ek = tuple(sorted([u, v]))
                    vc = visited_edges.get(ek, 0)
                    return PathUtils.flat_edge_weight(u, v, d) * (1 + vc * 2)

                return_path = nx.shortest_path(G, current, start_node, weight=return_weight)
                for n in return_path[1:]:
                    total_dist += (G.get_edge_data(path_nodes[-1], n) or {}).get("length", 0)
                    path_nodes.append(n)
            except nx.NetworkXNoPath:
                pass

        path_nodes = PathUtils.prune_dead_ends(path_nodes, G)
        return RouteOutput(
            mode="flat_circular",
            coordinates=PathUtils.extract_coordinates(G, path_nodes),
        )

    @staticmethod
    def _angle_to(G, a, b) -> float:
        """
        두 노드 간의 방위각(0~360도)을 반환합니다.
        """
        dx = G.nodes[b].get("x", 0) - G.nodes[a].get("x", 0)
        dy = G.nodes[b].get("y", 0) - G.nodes[a].get("y", 0)
        return math.degrees(math.atan2(dx, dy)) % 360

    @staticmethod
    def _angle_diff(a, b) -> float:
        """
        두 방위각 사이의 최소 차이(0~180도)를 반환합니다.
        """
        d = abs(a - b) % 360
        return d if d <= 180 else 360 - d
