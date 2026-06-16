import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.features import build_landmark_weights
from src.route_engine.scoring import apply_weights
from src.route_engine.schema import CircularRouteInput, RouteOutput


class LandmarkCircularRoute:
    WEIGHTS = build_landmark_weights()

    def __init__(self):
        pass

    def run(self, inp: CircularRouteInput, G: nx.Graph, landmark_node: int) -> RouteOutput:
        """
        출발지에서 랜드마크를 경유한 뒤 출발지로 복귀하는 순환 경로를 생성합니다.
        왕복 시 서로 다른 경로를 사용하도록 1구간 엣지에 페널티를 부여합니다.
        """
        G = apply_weights(G, self.WEIGHTS)
        start_node = PathUtils.find_nearest_node(G, inp.start_lat, inp.start_lon)

        try:
            path1 = nx.shortest_path(G, start_node, landmark_node, weight="custom_score")

            original_weights = {}
            for i in range(len(path1) - 1):
                u, v = path1[i], path1[i + 1]
                if G.has_edge(u, v):
                    original_weights[(u, v)] = G[u][v]["custom_score"]
                    G[u][v]["custom_score"] = original_weights[(u, v)] * 100

            path2 = nx.shortest_path(G, landmark_node, start_node, weight="custom_score")

            for (u, v), old_w in original_weights.items():
                G[u][v]["custom_score"] = old_w

            full_path = path1[:-1] + path2
            return RouteOutput(
                mode="landmark_circular",
                coordinates=PathUtils.extract_coordinates(G, full_path),
            )

        except nx.NetworkXNoPath:
            return RouteOutput(mode="landmark_circular", coordinates=[], error="경로 없음")
        except Exception as e:
            return RouteOutput(mode="landmark_circular", coordinates=[], error=str(e))
