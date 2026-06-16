import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.features import build_flat_weights
from src.route_engine.schema import OnewayRouteInput, RouteOutput


class FlatOnewayRoute:
    WEIGHTS = build_flat_weights()

    def __init__(self):
        pass

    def run(self, inp: OnewayRouteInput, G: nx.Graph) -> RouteOutput:
        """
        경사가 낮은 구간을 우선하여 출발지에서 도착지까지 편도 경로를 생성합니다.
        """
        start_node = PathUtils.find_nearest_node(G, inp.start_lat, inp.start_lon)
        end_node = PathUtils.find_nearest_node(G, inp.end_lat, inp.end_lon)

        try:
            path_nodes = nx.shortest_path(G, start_node, end_node, weight=PathUtils.flat_edge_weight)
        except (nx.NetworkXNoPath, Exception) as e:
            return RouteOutput(mode="flat_oneway", coordinates=[], error=str(e))

        return RouteOutput(
            mode="flat_oneway",
            coordinates=PathUtils.extract_coordinates(G, path_nodes),
        )
