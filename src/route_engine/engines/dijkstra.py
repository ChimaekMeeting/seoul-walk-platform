import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.profiles import get_profile
from src.interfaces.schema.walk_schema import (
    FallbackReason,
    WalkMode,
    WalkRouteResponse
)
from src.schema.route_schema import OnewayRouteInput
from src.route_engine.scoring.scoring_engine import calculate_custom_score


class OnewayDijkstraEngine:
    def __init__(
        self,
        inp: OnewayRouteInput,
        G: nx.Graph
    ):
        self.inp          = inp
        self.G            = G.copy()  # 원본 그래프 보호
        self.utils        = PathUtils(self.G)
        self.mode         = WalkMode.ONEWAY_SHORTEST
        profile           = get_profile("default")
        self.weights      = profile.weights
        self.blocked_tags = profile.blocked_tags

    def run(self) -> WalkRouteResponse:
        """
        Dijkstra 최단 경로를 생성합니다.
        """
        # 엣지별 custom_score 기록 (in-place)
        calculate_custom_score(self.G, {
            "mode": "general",
            "weights": self.weights,
            "blocked_tags": self.blocked_tags,
        })

        # 출발 노드와 도착 노드 탐색
        start = self.utils.find_nearest_node(self.inp.start_lat, self.inp.start_lon)
        end   = self.utils.find_nearest_node(self.inp.end_lat,   self.inp.end_lon)

        # 출발 노드가 없는 경우
        if start is None:
            return WalkRouteResponse(
            status="FAILED",
            mode=self.mode,
            coordinates=[],
            total_km=0.0,
            fallback_reason=FallbackReason.NO_NEAREST_START_NODE
        )
        
        # 도착 노드가 없는 경우
        if end is None:
            return WalkRouteResponse(
                status="FAILED",
                mode=self.mode,
                coordinates=[],
                total_km=0.0,
                fallback_reason=FallbackReason.NO_NEAREST_END_NODE
            )
        
        # 경로 생성
        nodes = self.find_path(start, end)

        # 경로가 없는 경우
        if not nodes:
            return WalkRouteResponse(
                status="FAILED",
                mode=self.mode,
                coordinates=[],
                total_km=0.0,
                fallback_reason=FallbackReason.NO_PATH
            )

        coords    = self.utils.extract_coordinates(nodes)  # [lat, lon] 좌표 목록
        total_m   = self.utils.calc_distance(nodes)        # 총 이동 거리(m)

        return WalkRouteResponse(
            status          = "SUCCESS" if coords else "FAILED",
            mode            = self.mode,
            coordinates     = coords,
            total_km        = round(total_m / 1000, 2),
            fallback_reason = None,
        )

    def find_path(self, start: int, end: int) -> list[int]:
        """
        Dijkstra 알고리즘으로 최단 경로 노드 목록을 반환합니다.
        """
        try:
            return nx.shortest_path(self.G, start, end, weight="custom_score")
        except nx.NetworkXNoPath:
            return []
        except Exception as e:
            print(f"[dijkstra] 오류: {e}")
            return []