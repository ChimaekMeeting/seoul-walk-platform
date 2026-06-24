import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.profiles import get_profile
from src.interfaces.schema.walk_schema import WalkRouteStatus, OnewayMode, WalkRouteResponse
from src.schema.route_schema import OnewayRouteInput


class OnewayFlatEngine:
    def __init__(self, inp: OnewayRouteInput, G: nx.Graph, mode: OnewayMode = OnewayMode.FLAT):
        self._inp          = inp
        self._G            = G.copy()  # 원본 그래프 보호
        self._utils        = PathUtils(self._G)
        self.mode          = mode
        profile            = get_profile("flat")
        self._weights      = profile.weights
        self._blocked_tags = profile.blocked_tags

    def run(self) -> WalkRouteResponse:
        """
        평지(slope_score 높은 엣지)를 선호하는 편도 경로를 생성합니다.
        """
        # 엣지별 custom_score 기록 (in-place)
        calculate_custom_score(self._G, {
            "mode": "general",
            "weights": self._weights,
            "blocked_tags": self._blocked_tags,
        })

        # 출발 노드와 도착 노드 탐색
        start = self._utils.find_nearest_node(self._inp.start_lat, self._inp.start_lon)
        end   = self._utils.find_nearest_node(self._inp.end_lat,   self._inp.end_lon)

        # 출발 노드가 없는 경우
        if start is None:
            return WalkRouteResponse(status=WalkRouteStatus.NO_NEAREST_START_NODE, mode=self.mode,
                               coordinates=[], total_km=0.0)
        if end is None:
            return WalkRouteResponse(status=WalkRouteStatus.NO_NEAREST_END_NODE, mode=self.mode,
                               coordinates=[], total_km=0.0)

        # 경로가 없는 경우
        if not nodes:
            return WalkRouteResponse(status=WalkRouteStatus.NO_PATH, mode=self.mode,
                               coordinates=[], total_km=0.0)

        self.avg_slope_score = self._calc_avg_slope(nodes)
        coords  = self._utils.extract_coordinates(nodes)
        total_m = self._calc_distance(nodes)
        return WalkRouteResponse(
            status      = WalkRouteStatus.SUCCESS if coords else WalkRouteStatus.NO_PATH,
            mode        = self.mode,
            coordinates = coords,
            total_km    = round(total_m / 1000, 2),
        )

    def _edge_cost(self, u: int, v: int, data: dict) -> float:
        """
        엣지의 평지 비용을 계산합니다. cost = length × (2 − slope)²
        """
        length = data.get("length", 1.0) or 1.0
        # slope > 1.0이면 (2.0-slope)^2 < 1이 되어 평지보다 낮은 cost가 나오는 역효과 방지
        slope  = max(0.0, min(1.0, data.get("slope_score", 0.5) or 0.5))
        return length * (2.0 - slope) ** 2

    def _find_path(self, start: int, end: int) -> list[int]:
        """
        평지 비용 기준 Dijkstra로 최단 경로 노드 목록을 반환합니다.
        """
        try:
            return nx.shortest_path(self._G, start, end, weight=self._edge_cost)
        except (nx.NetworkXNoPath, Exception) as e:
            print(f"[flat/oneway] 오류: {e}")
            return []

    def _calc_distance(self, nodes: list[int]) -> float:
        """
        노드 목록의 총 이동 거리(미터)를 반환합니다.
        """
        return sum(
            (self._G.get_edge_data(nodes[i], nodes[i + 1]) or {}).get("length", 0)
            for i in range(len(nodes) - 1)
        )

    def _calc_avg_slope(self, nodes: list[int]) -> float:
        """
        경로의 평균 경사 점수를 반환합니다.
        """
        scores = [
            (self._G.get_edge_data(nodes[i], nodes[i + 1]) or {}).get("slope_score", 0.5) or 0.5
            for i in range(len(nodes) - 1)
        ]
        return round(sum(scores) / len(scores), 4) if scores else 0.0


