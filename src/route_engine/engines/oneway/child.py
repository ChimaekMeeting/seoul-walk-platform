import networkx as nx

from src.repository.layer.child_repository import ChildRepository
from src.route_engine.engines.child_utils import annotate_child_friendliness
from src.route_engine.engines.oneway.random import RandomOnewayRoute
from src.route_engine.features import build_child_weights
from src.route_engine.schema import OnewayRouteInput, RouteOutput


class ChildOnewayRoute:
    WEIGHTS = build_child_weights()

    def __init__(self, G: nx.Graph, corridor_radius_m: float = 250.0):
        self._corridor_radius_m = corridor_radius_m
        # 편도 경로 생성용 엔진 초기화
        self._engine = RandomOnewayRoute(G)

    def run(self, inp: OnewayRouteInput) -> RouteOutput:
        """
        아이 동반 편도 경로를 생성하고 아이 친화도를 반영합니다.
        """
        # 주변 아이 관련 장소 조회
        places = self._load_child_places(inp)

        # 편도 경로 생성
        result = self._engine.run(inp)
        if result.error:
            return result

        # 아이 친화도 평가
        self._annotate(result, places)

        return RouteOutput(mode="child_oneway", coordinates=result.coordinates)

    def _load_child_places(self, inp: OnewayRouteInput) -> list[dict]:
        """
        출발지 반경 내 어린이 관련 장소 목록을 조회합니다.
        """
        # 탐색 반경 계산
        search_radius_m = max((inp.target_km or 3.0) * 1000 * 1.5, 1500.0)
        return ChildRepository.get_child_places_near(inp.start_lat, inp.start_lon, search_radius_m)

    def _annotate(self, result: RouteOutput, places: list[dict]) -> None:
        """
        생성된 경로에 아이 친화도 정보를 부여합니다.
        """
        annotate_child_friendliness(result.model_dump(), places, self._corridor_radius_m)
