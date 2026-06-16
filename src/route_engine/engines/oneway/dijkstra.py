import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.schema import OnewayRouteInput, RouteOutput


class DijkstraOnewayRoute:

    def __init__(self, G: nx.Graph):
        self.G = G

    def run(self, inp: OnewayRouteInput) -> RouteOutput:
        """
        출발지에서 도착지까지 최단 경로를 반환합니다.
        """
        # 출발·도착 노드 탐색
        start_node = PathUtils.find_nearest_node(self.G, inp.start_lat, inp.start_lon)
        end_node = PathUtils.find_nearest_node(self.G, inp.end_lat, inp.end_lon)

        # 최단 경로 탐색
        path_nodes = self._find_shortest_path(start_node, end_node)
        if path_nodes is None:
            return RouteOutput(mode="dijkstra_oneway", coordinates=[], error="경로 없음")

        return RouteOutput(
            mode="dijkstra_oneway",
            coordinates=PathUtils.extract_coordinates(self.G, path_nodes),
        )

    def _find_shortest_path(self, start_node: int, end_node: int) -> list | None:
        """
        두 노드 사이의 최단 경로 노드 목록을 반환합니다.
        """
        try:
            return nx.shortest_path(self.G, start_node, end_node, weight="length")
        except (nx.NetworkXNoPath, Exception):
            return None
