import math
import random

import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.engines.oneway.dijkstra import DijkstraOnewayRoute
from src.route_engine.features import build_random_weights
from src.route_engine.schema import OnewayRouteInput, RouteOutput
from src.route_engine.scoring import apply_weights


class RandomOnewayRoute:
    WEIGHTS = build_random_weights()

    def __init__(self, G: nx.Graph):
        # 엣지 가중치 적용
        apply_weights(G, self.WEIGHTS)
        self.G = G

    def run(self, inp: OnewayRouteInput) -> RouteOutput:
        """
        중간 경유지를 경유하는 우회 편도 경로를 생성합니다.
        1구간에서 사용한 엣지에 페널티를 부여해 2구간이 다른 길을 선택하도록 유도합니다.
        """
        # 출발·도착 노드 탐색
        start_node = PathUtils.find_nearest_node(self.G, inp.start_lat, inp.start_lon)
        end_node = PathUtils.find_nearest_node(self.G, inp.end_lat, inp.end_lon)
        target_m = (inp.target_km or 3.0) * 1000

        # 경유지 선택
        waypoint = self._select_waypoint(start_node, end_node, target_m)

        try:
            # 출발지 → 경유지 → 도착지 경로 탐색
            full_path = self._path_via_waypoint(start_node, waypoint, end_node)
            return RouteOutput(
                mode="random_oneway",
                coordinates=PathUtils.extract_coordinates(self.G, full_path),
            )
        except Exception:
            # 경로 탐색 실패 시 최단 경로로 대체
            return DijkstraOnewayRoute(self.G).run(inp)

    def _select_waypoint(self, start_node: int, end_node: int, target_m: float) -> int:
        """
        목표 거리 조건을 만족하는 경유지 후보 중 최적 노드를 선택합니다.
        """
        p1 = self.G.nodes[start_node]
        p2 = self.G.nodes[end_node]

        # 거리 조건을 만족하는 후보 노드 수집
        candidates = []
        for node, data in self.G.nodes(data=True):
            if node in [start_node, end_node]:
                continue
            d1 = math.sqrt((data["x"] - p1["x"]) ** 2 + (data["y"] - p1["y"]) ** 2) * 111000
            d2 = math.sqrt((data["x"] - p2["x"]) ** 2 + (data["y"] - p2["y"]) ** 2) * 111000
            total_straight = d1 + d2
            if (target_m * 0.6) <= total_straight <= (target_m * 0.9):
                candidates.append((node, abs(total_straight - target_m * 0.8)))

        if not candidates:
            # 후보 없을 경우 중간 지점 근처 노드 사용
            return PathUtils.find_nearest_node(
                self.G,
                (p1["y"] + p2["y"]) / 2 + 0.005,
                (p1["x"] + p2["x"]) / 2 + 0.005,
            )

        # 오차가 작은 상위 5개 중 랜덤 선택
        candidates.sort(key=lambda x: x[1])
        return random.choice(candidates[:5])[0]

    def _path_via_waypoint(self, start_node: int, waypoint: int, end_node: int) -> list:
        """
        경유지를 거치는 2구간 경로를 탐색합니다. 1구간 엣지에 페널티를 부여해 우회를 유도합니다.
        """
        # 1구간 탐색
        path1 = nx.shortest_path(self.G, start_node, waypoint, weight="custom_score")

        # 1구간 엣지 가중치 저장 및 페널티 적용
        saved: dict = {}
        for i in range(len(path1) - 1):
            u, v = path1[i], path1[i + 1]
            if self.G.has_edge(u, v):
                saved[(u, v)] = self.G[u][v]["custom_score"]
                self.G[u][v]["custom_score"] = saved[(u, v)] * 100

        # 2구간 탐색
        path2 = nx.shortest_path(self.G, waypoint, end_node, weight="custom_score")

        # 1구간 엣지 가중치 복원
        for (u, v), w in saved.items():
            self.G[u][v]["custom_score"] = w

        return path1[:-1] + path2
