import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.profiles import get_profile
from src.interfaces.schema.walk_schema import (
    FallbackReason,
    OnewayMode,
    WalkRouteResponse
)
from src.schema.route_schema import OnewayRouteInput
from src.route_engine.scoring.scoring_engine import calculate_custom_score


class OnewayDijkstraEngine:
    def __init__(
        self,
        inp: OnewayRouteInput,
        G: nx.Graph,
        mode: OnewayMode = OnewayMode.SHORTEST
    ):
        self._inp          = inp
        self._G            = G.copy()  # 원본 그래프 보호
        self._utils        = PathUtils(self._G)
        self.mode          = mode
        profile            = get_profile(self.mode)
        self._weights      = profile.weights
        self._blocked_tags = profile.blocked_tags

    def run(self) -> WalkRouteResponse:
        """
        Dijkstra 최단 경로를 생성합니다.
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
            return WalkRouteResponse(status="FAILED", mode=self.mode,
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_NEAREST_START_NODE)
        
        # 도착 노드가 없는 경우
        if end is None:
            return WalkRouteResponse(status="FAILED", mode=self.mode,
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_NEAREST_END_NODE)
        
        # 경로 생성
        nodes = self._find_path(start, end)

        # 경로가 없는 경우
        if not nodes:
            return WalkRouteResponse(status="FAILED", mode=self.mode,
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_PATH)

        coords  = self._utils.extract_coordinates(nodes)  # [lat, lon] 좌표 목록
        total_m = self._utils.calc_distance(nodes)        # 총 이동 거리(미터)
        if len(coords) < 2 or total_m <= 0:
            return WalkRouteResponse(status="FAILED", mode=self.mode,
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_PATH)

        return WalkRouteResponse(
            status          = "SUCCESS",
            mode            = self.mode,
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
