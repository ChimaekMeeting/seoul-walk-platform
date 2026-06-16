import networkx as nx

from src.repository.layer.child_repository import ChildRepository
from src.route_engine.engines.child_utils import annotate_child_friendliness
from src.route_engine.engines.oneway.random import RandomOnewayRoute
from src.route_engine.features import build_child_weights
from src.route_engine.schema import OnewayRouteInput, RouteOutput


class ChildOnewayRoute:
    WEIGHTS = build_child_weights()

    def __init__(self, corridor_radius_m: float = 250.0):
        self._corridor_radius_m = corridor_radius_m

    def run(self, inp: OnewayRouteInput, G: nx.Graph) -> RouteOutput:
        """
        아이 동반 편도 경로를 생성하고 아이 친화도를 반영합니다.
        """
        search_radius_m = max((inp.target_km or 3.0) * 1000 * 1.5, 1500.0)
        places = ChildRepository.get_child_places_near(inp.start_lat, inp.start_lon, search_radius_m)

        result = RandomOnewayRoute().run(inp, G)
        if result.error:
            return result
        annotate_child_friendliness(result.model_dump(), places, self._corridor_radius_m)
        return RouteOutput(mode="child_oneway", coordinates=result.coordinates)
