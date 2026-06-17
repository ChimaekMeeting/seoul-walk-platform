import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.profiles import get_profile
from src.schema.route_schema import FallbackReason, OnewayMode, OnewayRouteInput, RouteOutput
from src.route_engine.scoring.scoring_engine import calculate_custom_score


class OnewayLandmarkEngine:
    def __init__(
        self,
        inp: OnewayRouteInput,
        G: nx.Graph,
        landmark_node: int,
        profile_name: OnewayMode = OnewayMode.LANDMARK
    ):
        self._inp           = inp
        self._G             = G.copy()  # 원본 그래프 보호
        self._utils         = PathUtils(self._G)
        self._landmark_node = landmark_node  # 경유 랜드마크 노드
        profile             = get_profile(profile_name)
        self._weights       = profile.weights
        self._blocked_tags  = profile.blocked_tags

    def run(self) -> RouteOutput:
        """
        랜드마크를 경유하는 편도 경로를 생성합니다.
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
            return RouteOutput(status="FAILED", mode="oneway_landmark",
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_NEAREST_START_NODE)
        
        # 도착 노드가 없는 경우
        if end is None:
            return RouteOutput(status="FAILED", mode="oneway_landmark",
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_NEAREST_END_NODE)
        
        # 경로 생성
        nodes = self._find_path(start, end)

        # 경로가 없는 경우
        if not nodes:
            return RouteOutput(status="FAILED", mode="oneway_landmark",
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_PATH)

        coords  = self._utils.extract_coordinates(nodes)  # [lat, lon] 좌표 목록
        total_m = self._utils.calc_distance(nodes)        # 총 이동 거리(미터)

        return RouteOutput(
            status          = "SUCCESS" if coords else "FAILED",
            mode            = "oneway_landmark",
            coordinates     = coords,
            total_km        = round(total_m / 1000, 2),
            fallback_reason = None,
        )

    def _find_path(self, start: int, end: int) -> list[int]:
        """
        출발 → 랜드마크 → 도착 경로를 연결합니다.
        """
        try:
            path1 = nx.shortest_path(self._G, start, self._landmark_node, weight="custom_score")    # 출발 노드 -> 랜드마크 노드
            self._penalize(path1)                                                                   # 1구간 엣지 페널티
            path2 = nx.shortest_path(self._G, self._landmark_node, end, weight="custom_score")      # 랜드마크 노드 -> 도착 노드
            return path1[:-1] + path2  # 랜드마크 노드 중복 제거 후 연결
        except nx.NetworkXNoPath:
            print(f"[landmark/oneway] 경로 없음: {start} → {self._landmark_node} → {end}")
            return []
        except Exception as e:
            print(f"[landmark/oneway] 오류: {e}")
            return []

    def _penalize(self, path: list[int]) -> None:
        """
        경로 엣지에 재사용 억제 페널티(×100)를 적용합니다.
        """
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            if self._G.has_edge(u, v):
                self._G[u][v]["custom_score"] *= 100  # 재사용 억제 페널티