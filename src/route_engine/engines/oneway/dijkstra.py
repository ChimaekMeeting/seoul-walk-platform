import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.schema import OnewayRouteInput, RouteOutput


class DijkstraOnewayRoute:

    def __init__(self):
        pass

    def run(self, inp: OnewayRouteInput, G: nx.Graph) -> RouteOutput:
        """
        출발지에서 도착지까지 최단 경로를 반환합니다.
        """
        start_node = PathUtils.find_nearest_node(G, inp.start_lat, inp.start_lon)
        end_node = PathUtils.find_nearest_node(G, inp.end_lat, inp.end_lon)

        try:
            path_nodes = nx.shortest_path(G, start_node, end_node, weight="custom_score")
            return RouteOutput(
                mode="dijkstra_oneway",
                coordinates=PathUtils.extract_coordinates(G, path_nodes),
            )
        except nx.NetworkXNoPath:
            return RouteOutput(mode="dijkstra_oneway", coordinates=[], error="경로 없음")
        except Exception as e:
            return RouteOutput(mode="dijkstra_oneway", coordinates=[], error=str(e))
