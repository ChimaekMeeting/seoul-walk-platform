import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.features import build_landmark_weights
from src.route_engine.schema import OnewayRouteInput, RouteOutput
from src.route_engine.scoring import apply_weights


class LandmarkOnewayRoute:
    WEIGHTS = build_landmark_weights()

    def __init__(self, G: nx.Graph):
        # 엣지 가중치 적용
        apply_weights(G, self.WEIGHTS)
        self.G = G

    def run(self, inp: OnewayRouteInput, landmark_node: int) -> RouteOutput:
        """
        출발지에서 랜드마크를 경유하여 도착지까지 이동하는 편도 경로를 생성합니다.
        """
        # 출발·도착 노드 탐색
        start_node = PathUtils.find_nearest_node(self.G, inp.start_lat, inp.start_lon)
        end_node = PathUtils.find_nearest_node(self.G, inp.end_lat, inp.end_lon)

        try:
            # 출발지 → 랜드마크 경로 탐색 및 페널티 적용
            path1, saved_weights = self._path_to_landmark(start_node, landmark_node)

            # 랜드마크 → 도착지 경로 탐색 및 페널티 복원
            path2 = self._path_from_landmark(landmark_node, end_node, saved_weights)

            # 전체 경로 조합
            full_path = path1[:-1] + path2
            return RouteOutput(
                mode="landmark_oneway",
                coordinates=PathUtils.extract_coordinates(self.G, full_path),
            )
        except nx.NetworkXNoPath:
            return RouteOutput(mode="landmark_oneway", coordinates=[], error="경로 없음")
        except Exception as e:
            return RouteOutput(mode="landmark_oneway", coordinates=[], error=str(e))

    def _path_to_landmark(self, start_node: int, landmark_node: int) -> tuple[list, dict]:
        """
        출발지에서 랜드마크까지 경로를 탐색하고 해당 엣지에 페널티를 부여합니다.
        """
        path = nx.shortest_path(self.G, start_node, landmark_node, weight="custom_score")

        # 1구간 엣지 가중치 저장 및 페널티 적용
        saved: dict = {}
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            if self.G.has_edge(u, v):
                saved[(u, v)] = self.G[u][v]["custom_score"]
                self.G[u][v]["custom_score"] = saved[(u, v)] * 100

        return path, saved

    def _path_from_landmark(
        self, landmark_node: int, end_node: int, saved_weights: dict
    ) -> list:
        """
        랜드마크에서 도착지까지 경로를 탐색하고 페널티를 복원합니다.
        """
        path = nx.shortest_path(self.G, landmark_node, end_node, weight="custom_score")

        # 1구간 엣지 가중치 복원
        for (u, v), w in saved_weights.items():
            self.G[u][v]["custom_score"] = w

        return path
