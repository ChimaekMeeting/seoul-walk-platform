import networkx as nx

from src.route_engine.engines.circular.random import RandomCircularRoute
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.features import build_running_weights
from src.route_engine.schema import CircularRouteInput, RouteOutput
from src.route_engine.scoring import apply_running_weights


class RunningCircularRoute:
    WEIGHTS = build_running_weights()

    def __init__(self, G: nx.Graph):
        # 유효하지 않은 노드 제거 및 러닝 가중치 적용
        G = self._prepare_graph(G)
        self.G = G

    def run(self, inp: CircularRouteInput) -> RouteOutput:
        """
        러닝 코스에 적합한 가중치를 적용한 뒤 순환 경로를 생성합니다.
        """
        if self.G.number_of_nodes() == 0:
            return RouteOutput(mode="circular_running", coordinates=[], error="유효한 노드가 없습니다.")

        # 랜덤 워크 기반 순환 경로 생성
        result = RandomCircularRoute(self.G).run(inp)
        return RouteOutput(mode="circular_running", coordinates=result.coordinates, error=result.error)

    def _prepare_graph(self, G: nx.Graph) -> nx.Graph:
        """
        유효하지 않은 노드를 제거하고 러닝 가중치를 엣지에 적용합니다.
        """
        # 좌표 없는 노드 제거
        G = PathUtils.remove_invalid_nodes(G)

        # 러닝 경로 가중치 적용
        G = apply_running_weights(G)
        return G
