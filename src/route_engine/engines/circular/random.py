import random

import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.features import build_random_weights
from src.route_engine.schema import CircularRouteInput, RouteOutput
from src.route_engine.scoring import apply_weights


class RandomCircularRoute:
    WEIGHTS = build_random_weights()

    def __init__(self, G: nx.Graph):
        # 엣지 가중치 적용
        apply_weights(G, self.WEIGHTS)
        self.G = G

    def run(self, inp: CircularRouteInput) -> RouteOutput:
        """
        출발지에서 목표 거리만큼 랜덤 워크 후 출발지로 복귀하는 순환 경로를 생성합니다.
        """
        # 시작 노드 및 목표 거리 설정
        start_node = PathUtils.find_nearest_node(self.G, inp.start_lat, inp.start_lon)
        target_m = (inp.target_km or 3.0) * 1000

        # 랜덤 워크 수행
        path_nodes, visited_edges = self._walk(start_node, target_m)

        # 출발지 복귀
        path_nodes = self._return_to_start(path_nodes, start_node, visited_edges)

        return RouteOutput(
            mode="random_circular",
            coordinates=PathUtils.extract_coordinates(self.G, path_nodes),
        )

    def _walk(self, start_node: int, target_m: float) -> tuple[list, dict]:
        """
        목표 거리에 도달할 때까지 랜덤 워크를 수행합니다.
        """
        start_x = self.G.nodes[start_node]["x"]
        start_y = self.G.nodes[start_node]["y"]
        path_nodes = [start_node]
        visited_edges: dict = {}
        total_distance = 0.0
        current = start_node

        while total_distance < target_m * 0.75:
            neighbors = list(self.G.neighbors(current))
            if not neighbors:
                break

            # 이웃 노드별 선택 확률 계산
            weights = []
            progress = total_distance / target_m
            for n in neighbors:
                edge_key = tuple(sorted([current, n]))
                edge_data = self.G.get_edge_data(current, n) or {}
                w = edge_data.get("custom_score", 1.0)

                # 출발지 이탈 보너스 (탐색 초기)
                if progress < 0.7:
                    nx_ = self.G.nodes[n]["x"]
                    ny_ = self.G.nodes[n]["y"]
                    dist_from_start = ((nx_ - start_x) ** 2 + (ny_ - start_y) ** 2) ** 0.5
                    w = w / ((dist_from_start + 1e-6) ** 2)

                # 재방문 페널티
                edge_penalty = 1.0 / (1 + visited_edges.get(edge_key, 0) * 7)
                degree_penalty = 1.0 / (1 + max(0, 3 - self.G.degree(n)))
                weights.append((1.0 / w) * edge_penalty * degree_penalty)

            # 다음 노드 선택
            total_w = sum(weights)
            probs = [w / total_w for w in weights]
            next_node = random.choices(neighbors, weights=probs, k=1)[0]

            # 이동 처리
            edge_key = tuple(sorted([current, next_node]))
            visited_edges[edge_key] = visited_edges.get(edge_key, 0) + 1
            edge_data = self.G.get_edge_data(current, next_node) or {}
            total_distance += edge_data.get("length", 0)
            path_nodes.append(next_node)
            current = next_node

        return path_nodes, visited_edges

    def _return_to_start(
        self, path_nodes: list, start_node: int, visited_edges: dict
    ) -> list:
        """
        현재 위치에서 출발지로 복귀하는 경로를 추가합니다.
        """
        if path_nodes[-1] == start_node:
            return path_nodes

        current = path_nodes[-1]

        try:
            def return_weight(u, v, d):
                # 기방문 엣지 페널티 반영
                ek = tuple(sorted([u, v]))
                vc = visited_edges.get(ek, 0)
                return d.get("length", 1.0) * (1 + vc * 10)

            return_path = nx.shortest_path(self.G, current, start_node, weight=return_weight)
            for n in return_path[1:]:
                path_nodes.append(n)
        except nx.NetworkXNoPath:
            pass

        return path_nodes
