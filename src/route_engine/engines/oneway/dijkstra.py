import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.profiles import get_profile
from src.route_engine.schema import FallbackReason, OnewayRouteInput, RouteOutput
from src.route_engine.scoring.scoring_engine import calculate_custom_score


class OnewayDijkstraEngine:
    def __init__(self, inp: OnewayRouteInput, G: nx.Graph, profile_name: str = "default"):
        self._inp          = inp
        self._G            = G.copy()  # 원본 그래프 보호
        self._utils        = PathUtils(self._G)
        profile            = get_profile(profile_name)
        self._weights      = profile.weights
        self._blocked_tags = profile.blocked_tags

    def run(self) -> RouteOutput:
        """
        Dijkstra 최단 경로를 생성합니다.
        """
        calculate_custom_score(self._G, {
            "mode": "general",
            "weights": self._weights,
            "blocked_tags": self._blocked_tags,
        })

        start = self._utils.find_nearest_node(self._inp.start_lat, self._inp.start_lon)
        end   = self._utils.find_nearest_node(self._inp.end_lat,   self._inp.end_lon)

        if start is None:
            return RouteOutput(status="FAILED", mode="oneway_dijkstra",
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_NEAREST_START_NODE)
        if end is None:
            return RouteOutput(status="FAILED", mode="oneway_dijkstra",
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_NEAREST_END_NODE)

        nodes = self._find_path(start, end)
        if not nodes:
            return RouteOutput(status="FAILED", mode="oneway_dijkstra",
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_PATH)

        target_km = self._inp.target_km or 3.0
        total_m   = self._calc_distance(nodes)

        # 최단경로가 목표의 60% 미만이면 우회 경로로 대체
        # 출발·도착이 가까울 때 지나치게 짧은 경로가 반환되는 문제 방지
        if total_m < target_km * 0.6 * 1000:
            fallback = self._utils.oneway_waypoint_path(start, end, target_km)
            if fallback:
                nodes   = fallback
                total_m = self._calc_distance(nodes)

        coords = self._utils.extract_coordinates(nodes)
        return RouteOutput(
            status          = "SUCCESS" if coords else "FAILED",
            mode            = "oneway_dijkstra",
            coordinates     = coords,
            total_km        = round(total_m / 1000, 2),
            fallback_reason = None,
        )

    def _find_path(self, start: int, end: int) -> list[int]:
        """
        Dijkstra 알고리즘으로 최단 경로 노드 목록을 반환합니다.
        """
        try:
            return nx.shortest_path(self._G, start, end, weight="custom_score")
        except nx.NetworkXNoPath:
            return []
        except Exception as e:
            print(f"[dijkstra] 오류: {e}")
            return []

    def _calc_distance(self, nodes: list[int]) -> float:
        """
        노드 목록의 총 이동 거리(미터)를 반환합니다.
        """
        return sum(
            (self._G.get_edge_data(nodes[i], nodes[i + 1]) or {}).get("length", 0)
            for i in range(len(nodes) - 1)
        )

