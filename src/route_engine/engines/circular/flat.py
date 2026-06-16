import math
import random

import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.features import build_flat_weights
from src.route_engine.schema import CircularRouteInput, RouteOutput

FLAT_THRESHOLD = 0.7


class FlatCircularRoute:
    WEIGHTS = build_flat_weights()

    def __init__(self, G: nx.Graph):
        self.G = G

    def run(self, inp: CircularRouteInput) -> RouteOutput:
        """
        경사가 낮은 구간을 우선 탐색하여 평지 중심의 순환 경로를 생성합니다.
        """
        # 목표 거리 및 시작 노드 설정
        target_m = inp.target_km * 1000
        start_node = PathUtils.find_nearest_node(self.G, inp.start_lat, inp.start_lon)

        # 평지 진입점 탐색 및 접근 경로 계산
        flat_nodes = self._find_flat_nodes()
        flat_entry, path_nodes, approach_dist = self._approach_flat_area(
            start_node, flat_nodes, target_m
        )

        # 평지 구간 랜덤 워크
        loop_target = max(target_m - approach_dist * 2, target_m * 0.5)
        path_nodes, visited_edges = self._flat_walk(flat_entry, path_nodes, loop_target)

        # 출발지 복귀
        path_nodes = self._return_to_start(path_nodes, start_node, visited_edges)

        # dead-end 제거 및 좌표 추출
        path_nodes = PathUtils.prune_dead_ends(path_nodes, self.G)
        return RouteOutput(
            mode="flat_circular",
            coordinates=PathUtils.extract_coordinates(self.G, path_nodes),
        )

    def _find_flat_nodes(self) -> set:
        """
        경사 점수가 임계값 이상인 엣지의 노드 집합을 반환합니다.
        """
        flat_nodes: set = set()
        for u, v, d in self.G.edges(data=True):
            if (d.get("slope_score") or 0) >= FLAT_THRESHOLD:
                flat_nodes.add(u)
                flat_nodes.add(v)
        return flat_nodes

    def _approach_flat_area(
        self, start_node: int, flat_nodes: set, target_m: float
    ) -> tuple[int, list, float]:
        """
        가장 가까운 평지 진입점까지 접근 경로를 계산합니다.
        """
        sx = self.G.nodes[start_node].get("x", 0)
        sy = self.G.nodes[start_node].get("y", 0)
        path_nodes = [start_node]
        total_dist = 0.0

        # 가장 가까운 평지 노드 탐색
        flat_entry = start_node
        if start_node not in flat_nodes and flat_nodes:
            min_dist = float("inf")
            for node in flat_nodes:
                nd = self.G.nodes[node]
                if "x" not in nd or "y" not in nd:
                    continue
                d = math.sqrt((nd["x"] - sx) ** 2 + (nd["y"] - sy) ** 2) * 111000
                if d < min_dist and d < target_m * 2:
                    min_dist = d
                    flat_entry = node

        # 진입점까지 경로 탐색
        if flat_entry != start_node:
            try:
                approach = nx.shortest_path(self.G, start_node, flat_entry, weight="length")
                for n in approach[1:]:
                    total_dist += (self.G.get_edge_data(path_nodes[-1], n) or {}).get("length", 0)
                    path_nodes.append(n)
            except nx.NetworkXNoPath:
                flat_entry = start_node

        return flat_entry, path_nodes, total_dist

    def _flat_walk(
        self, flat_entry: int, path_nodes: list, loop_target: float
    ) -> tuple[list, dict]:
        """
        평지 구간에서 방향성을 유지하며 랜덤 워크를 수행합니다.
        """
        current = flat_entry
        visited_edges: dict = {}
        loop_dist = 0.0
        heading = random.uniform(0, 360)

        while loop_dist < loop_target:
            neighbors = list(self.G.neighbors(current))
            if not neighbors:
                break

            # 이웃 노드별 선택 확률 계산
            probs = []
            for n in neighbors:
                edge_key = tuple(sorted([current, n]))
                edge_data = self.G.get_edge_data(current, n) or {}
                slope = edge_data.get("slope_score", 0.5) or 0.5
                visit_cnt = visited_edges.get(edge_key, 0)

                # 평지 선호 및 방향·재방문 가중치
                slope_w = slope if slope >= FLAT_THRESHOLD else 0.01
                ang = self._angle_to(self.G, current, n)
                dir_score = max(0.01, 1.0 - self._angle_diff(ang, heading) / 180.0)
                visit_pen = 1.0 / (1 + visit_cnt * 6)
                probs.append(slope_w * dir_score * visit_pen)

            total_p = sum(probs)
            if total_p == 0:
                break
            probs = [p / total_p for p in probs]

            # 다음 노드 선택 및 이동
            next_node = random.choices(neighbors, weights=probs, k=1)[0]
            edge_key = tuple(sorted([current, next_node]))
            visited_edges[edge_key] = visited_edges.get(edge_key, 0) + 1

            step = (self.G.get_edge_data(current, next_node) or {}).get("length", 0)
            loop_dist += step
            path_nodes.append(next_node)
            current = next_node

            # 진행 방향 업데이트
            cur_ang = self._angle_to(self.G, flat_entry, current)
            target_ang = (cur_ang + 90) % 360
            heading = (heading * 0.85 + target_ang * 0.15) % 360

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
                return PathUtils.flat_edge_weight(u, v, d) * (1 + vc * 2)

            return_path = nx.shortest_path(self.G, current, start_node, weight=return_weight)
            for n in return_path[1:]:
                path_nodes.append(n)
        except nx.NetworkXNoPath:
            pass

        return path_nodes

    @staticmethod
    def _angle_to(G: nx.Graph, a: int, b: int) -> float:
        """
        두 노드 간의 방위각(0~360도)을 반환합니다.
        """
        dx = G.nodes[b].get("x", 0) - G.nodes[a].get("x", 0)
        dy = G.nodes[b].get("y", 0) - G.nodes[a].get("y", 0)
        return math.degrees(math.atan2(dx, dy)) % 360

    @staticmethod
    def _angle_diff(a: float, b: float) -> float:
        """
        두 방위각 사이의 최소 차이(0~180도)를 반환합니다.
        """
        d = abs(a - b) % 360
        return d if d <= 180 else 360 - d
