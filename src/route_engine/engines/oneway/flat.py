import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.profiles import get_profile
from src.route_engine.schema import FallbackReason, OnewayRouteInput, RouteOutput


class OnewayFlatEngine:
    def __init__(self, inp: OnewayRouteInput, G: nx.Graph, profile_name: str = "flat"):
        self._inp          = inp
        self._G            = G.copy()  # 원본 그래프 보호
        self._utils        = PathUtils(self._G)
        profile            = get_profile(profile_name)
        self._weights      = profile.weights
        self._blocked_tags = profile.blocked_tags
        self.avg_slope_score: float = 0.0  # run() 이후 접근 가능

    def run(self) -> RouteOutput:
        """
        경사를 최소화한 평지 편도 경로를 생성합니다.
        """
        start = self._utils.find_nearest_node(self._inp.start_lat, self._inp.start_lon)
        end   = self._utils.find_nearest_node(self._inp.end_lat,   self._inp.end_lon)

        if start is None:
            return RouteOutput(status="FAILED", mode="oneway_flat",
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_NEAREST_START_NODE)
        if end is None:
            return RouteOutput(status="FAILED", mode="oneway_flat",
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_NEAREST_END_NODE)

        nodes = self._find_path(start, end)
        if not nodes:
            return RouteOutput(status="FAILED", mode="oneway_flat",
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_PATH)

        self.avg_slope_score = self._calc_avg_slope(nodes)
        coords  = self._utils.extract_coordinates(nodes)
        total_m = self._calc_distance(nodes)
        return RouteOutput(
            status          = "SUCCESS" if coords else "FAILED",
            mode            = "oneway_flat",
            coordinates     = coords,
            total_km        = round(total_m / 1000, 2),
            fallback_reason = None,
        )

    def _edge_cost(self, u: int, v: int, data: dict) -> float:
        """
        엣지의 평지 비용을 계산합니다. cost = length × (2 − slope)²
        """
        length = data.get("length", 1.0) or 1.0
        slope  = data.get("slope_score", 0.5) or 0.5
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


