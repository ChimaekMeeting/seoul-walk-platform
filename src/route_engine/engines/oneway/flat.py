import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.features import build_flat_weights
from src.route_engine.schema import OnewayRouteInput, RouteOutput


class FlatOnewayRoute:
    WEIGHTS = build_flat_weights()

    def __init__(self, G: nx.Graph):
        self.G = G

    def run(self, inp: OnewayRouteInput) -> RouteOutput:
        """
        경사가 낮은 구간을 우선하여 출발지에서 도착지까지 편도 경로를 생성합니다.
        """
        # 출발·도착 노드 탐색
        start_node = PathUtils.find_nearest_node(self.G, inp.start_lat, inp.start_lon)
        end_node = PathUtils.find_nearest_node(self.G, inp.end_lat, inp.end_lon)

        # 평지 우선 경로 탐색
        path_nodes = self._find_flat_path(start_node, end_node)
        if path_nodes is None:
            return RouteOutput(mode="flat_oneway", coordinates=[], error="경로 없음")

        return RouteOutput(
            mode="flat_oneway",
            coordinates=PathUtils.extract_coordinates(self.G, path_nodes),
        )

    def _find_flat_path(self, start_node: int, end_node: int) -> list | None:
        """
        경사 기반 가중치를 적용한 최단 경로 노드 목록을 반환합니다.
        """
        try:
            return nx.shortest_path(self.G, start_node, end_node, weight=PathUtils.flat_edge_weight)
        except (nx.NetworkXNoPath, Exception):
            return None
