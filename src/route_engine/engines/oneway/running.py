import networkx as nx

from src.route_engine.engines.oneway.dijkstra import DijkstraOnewayRoute
from src.route_engine.engines.oneway.random import RandomOnewayRoute
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.features import build_running_weights
from src.route_engine.scoring import apply_running_weights
from src.route_engine.schema import OnewayRouteInput, RouteOutput


class RunningOnewayRoute:
    WEIGHTS = build_running_weights()

    def __init__(self):
        pass

    def run(self, inp: OnewayRouteInput, G: nx.Graph) -> RouteOutput:
        """
        러닝 코스에 적합한 가중치를 적용한 뒤 편도 경로를 생성합니다.
        목표 거리가 지정된 경우 우회 경로를, 아닌 경우 최단 경로를 반환합니다.
        """
        G = PathUtils.remove_invalid_nodes(G)
        if G.number_of_nodes() == 0:
            return RouteOutput(mode="oneway_running", coordinates=[], error="유효한 노드가 없습니다.")
        G = apply_running_weights(G)
        if inp.target_km:
            result = RandomOnewayRoute().run(inp, G)
        else:
            result = DijkstraOnewayRoute().run(inp, G)
        return RouteOutput(mode="oneway_running", coordinates=result.coordinates, error=result.error)
