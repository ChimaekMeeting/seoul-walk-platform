import networkx as nx

from src.route_engine.engines.oneway.dijkstra import DijkstraOnewayRoute
from src.route_engine.engines.oneway.random import RandomOnewayRoute
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.features import build_running_weights
from src.route_engine.schema import OnewayRouteInput, RouteOutput
from src.route_engine.scoring import apply_running_weights


class RunningOnewayRoute:
    WEIGHTS = build_running_weights()

    def __init__(self, G: nx.Graph):
        # 유효하지 않은 노드 제거 및 러닝 가중치 적용
        G = self._prepare_graph(G)
        self.G = G

    def run(self, inp: OnewayRouteInput) -> RouteOutput:
        """
        러닝 코스에 적합한 가중치를 적용한 뒤 편도 경로를 생성합니다.
        목표 거리가 지정된 경우 우회 경로를, 아닌 경우 최단 경로를 반환합니다.
        """
        if self.G.number_of_nodes() == 0:
            return RouteOutput(mode="oneway_running", coordinates=[], error="유효한 노드가 없습니다.")

        # 목표 거리 유무에 따라 엔진 선택
        result = self._route(inp)
        return RouteOutput(mode="oneway_running", coordinates=result.coordinates, error=result.error)

    def _prepare_graph(self, G: nx.Graph) -> nx.Graph:
        """
        유효하지 않은 노드를 제거하고 러닝 가중치를 엣지에 적용합니다.
        """
        # 좌표 없는 노드 제거
        G = PathUtils.remove_invalid_nodes(G)

        # 러닝 경로 가중치 적용
        G = apply_running_weights(G)
        return G

    def _route(self, inp: OnewayRouteInput) -> RouteOutput:
        """
        목표 거리 유무에 따라 우회 경로 또는 최단 경로를 반환합니다.
        """
        if inp.target_km:
            # 목표 거리 지정 시 우회 경로
            return RandomOnewayRoute(self.G).run(inp)

        # 목표 거리 미지정 시 최단 경로
        return DijkstraOnewayRoute(self.G).run(inp)
