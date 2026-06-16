import networkx as nx

from src.repository.layer.child_repository import ChildRepository
from src.route_engine.engines.child_utils import annotate_child_friendliness
from src.route_engine.engines.circular.random import RandomCircularRoute
from src.route_engine.features import build_child_weights
from src.route_engine.schema import CircularRouteInput, RouteOutput


class ChildCircularRoute:
    WEIGHTS = build_child_weights()

    def __init__(self, G: nx.Graph, candidate_count: int = 5, corridor_radius_m: float = 250.0):
        self._candidate_count = candidate_count
        self._corridor_radius_m = corridor_radius_m
        # 후보 경로 생성용 엔진 초기화
        self._engine = RandomCircularRoute(G)

    def run(self, inp: CircularRouteInput) -> RouteOutput:
        """
        아이 동반 순환 경로를 생성합니다. 후보 경로 중 아이 친화도가 가장 높은 경로를 반환합니다.
        """
        # 주변 아이 관련 장소 조회
        places = self._load_child_places(inp)

        # 후보 경로 중 최적 경로 선택
        return self._select_best_route(inp, places)

    def _load_child_places(self, inp: CircularRouteInput) -> list[dict]:
        """
        출발지 반경 내 어린이 관련 장소 목록을 조회합니다.
        """
        # 탐색 반경 계산
        search_radius_m = max((inp.target_km or 3.0) * 1000 * 1.5, 1500.0)
        return ChildRepository.get_child_places_near(inp.start_lat, inp.start_lon, search_radius_m)

    def _select_best_route(self, inp: CircularRouteInput, places: list[dict]) -> RouteOutput:
        """
        후보 경로를 생성하고 아이 친화도가 가장 높은 경로를 반환합니다.
        """
        best_route: RouteOutput | None = None
        best_index = -1.0

        for _ in range(self._candidate_count):
            # 후보 경로 생성
            result = self._engine.run(inp)
            if result.error:
                return result

            # 아이 친화도 평가
            annotated = annotate_child_friendliness(
                result.model_dump(), places, self._corridor_radius_m
            )
            index = annotated.get("child_index", 0.0)

            # 최고 친화도 경로 갱신
            if index > best_index:
                best_index = index
                best_route = RouteOutput(mode="child_circular", coordinates=result.coordinates)

        return best_route or RouteOutput(
            mode="child_circular",
            coordinates=[],
            error="아이 동반 순환 경로를 계산하지 못했습니다.",
        )
