import networkx as nx

from src.route_engine.engines.circular.random import RandomCircularRoute
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.features import build_running_weights
from src.route_engine.scoring import apply_running_weights
from src.route_engine.schema import CircularRouteInput, RouteOutput


class RunningCircularRoute:
    WEIGHTS = build_running_weights()

    def __init__(self):
        pass

    def run(self, inp: CircularRouteInput, G: nx.Graph) -> RouteOutput:
        """
        러닝 코스에 적합한 가중치를 적용한 뒤 순환 경로를 생성합니다.
        """
        G = PathUtils.remove_invalid_nodes(G)
        if G.number_of_nodes() == 0:
            return RouteOutput(mode="circular_running", coordinates=[], error="유효한 노드가 없습니다.")
        G = apply_running_weights(G)
        result = RandomCircularRoute().run(inp, G)
        return RouteOutput(mode="circular_running", coordinates=result.coordinates, error=result.error)
