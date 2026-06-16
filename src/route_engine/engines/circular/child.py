import networkx as nx

from src.repository.layer.child_repository import ChildRepository
from src.route_engine.engines.child_utils import annotate_child_friendliness
from src.route_engine.engines.circular.random import RandomCircularRoute
from src.route_engine.features import build_child_weights
from src.route_engine.schema import CircularRouteInput, RouteOutput


class ChildCircularRoute:
    WEIGHTS = build_child_weights()

    def __init__(self, candidate_count: int = 5, corridor_radius_m: float = 250.0):
        self._candidate_count = candidate_count
        self._corridor_radius_m = corridor_radius_m

    def run(self, inp: CircularRouteInput, G: nx.Graph) -> RouteOutput:
        """
        아이 동반 순환 경로를 생성합니다. 후보 경로 중 아이 친화도가 가장 높은 경로를 반환합니다.
        """
        search_radius_m = max((inp.target_km or 3.0) * 1000 * 1.5, 1500.0)
        places = ChildRepository.get_child_places_near(inp.start_lat, inp.start_lon, search_radius_m)

        engine = RandomCircularRoute()
        best_route: RouteOutput | None = None
        best_index = -1.0

        for _ in range(self._candidate_count):
            result = engine.run(inp, G)
            if result.error:
                return result
            annotated = annotate_child_friendliness(result.model_dump(), places, self._corridor_radius_m)
            index = annotated.get("child_index", 0.0)
            if index > best_index:
                best_index = index
                best_route = RouteOutput(mode="child_circular", coordinates=result.coordinates)

        return best_route or RouteOutput(
            mode="child_circular",
            coordinates=[],
            error="아이 동반 순환 경로를 계산하지 못했습니다.",
        )
