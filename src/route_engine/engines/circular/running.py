import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.profiles import get_profile
from src.interfaces.schema.walk_schema import (
    CircularMode,
    FallbackReason,
    WalkRouteResponse
)
from src.schema.route_schema import CircularRouteInput
from src.route_engine.scoring.scoring_engine import calculate_custom_score

class CircularRunningEngine:
    def __init__(
        self,
        inp: CircularRouteInput,
        G: nx.Graph,
        mode: CircularMode = CircularMode.RUNNING
    ):
        self._inp          = inp
        self._G            = G.copy()         # 원본 그래프 보호
        self._utils        = PathUtils(self._G)
        self.mode          = mode
        profile            = get_profile(self.mode)
        self._weights      = profile.weights
        self._blocked_tags = profile.blocked_tags

    def run(self) -> WalkRouteResponse:
        """
        DB 코스 정보를 반영한 순환 런닝 경로를 생성합니다.
        """
        # 엣지별 custom_score 기록 (in-place)
        calculate_custom_score(self._G, {
            "mode": "running",
            "weights": self._weights,
            "blocked_tags": self._blocked_tags,
        })

        # 출발 노드 탐색
        start = self._utils.find_nearest_node(self._inp.start_lat, self._inp.start_lon)

        # 출발 노드가 없는 경우
        if start is None:
            return WalkRouteResponse(status="FAILED", mode=self.mode,
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_NEAREST_START_NODE)
        
        # 경로 생성
        nodes = self._utils.circular_random_walk(start, self._inp.target_km or 5.0)

        # 경로가 없는 경우
        if not nodes:
            return WalkRouteResponse(status="FAILED", mode=self.mode,
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_PATH)

        pruned  = self._utils.prune_dead_ends(nodes, max_branch_length=300)  # 왕복 가지 제거
        total_m = self._utils.calc_distance(pruned)                          # 총 이동 거리(미터)
        if total_m <= 0:
            # Pruning can collapse short out-and-back walks to the start node only.
            # Keep the generated route instead of reporting a misleading 0 km success.
            pruned = nodes
            total_m = self._utils.calc_distance(pruned)
        coords  = self._utils.extract_coordinates(pruned)                    # [lat, lon] 좌표 목록
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
