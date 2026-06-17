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


class CircularFlatEngine:
    def __init__(
        self,
        inp: CircularRouteInput,
        G: nx.Graph,
        mode: CircularMode = CircularMode.FLAT
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
        평지(slope_score 높은 엣지)를 선호하는 순환 경로를 생성합니다.
        """
        # 엣지별 custom_score 기록 (in-place) — flat 프로필은 slope=1.0으로 평지 선호
        calculate_custom_score(self._G, {
            "mode": "general",
            "weights": self._weights,
            "blocked_tags": self._blocked_tags,
        })

        # 출발 노드 탐색
        start = self._utils.find_nearest_node(self._inp.start_lat, self._inp.start_lon)

        # 출발 노드가 없는 경우
        if start is None:
            return WalkRouteResponse(
                status="FAILED",
                mode=self.mode,
                coordinates=[],
                total_km=0.0,
                fallback_reason=FallbackReason.NO_NEAREST_START_NODE,
            )

        # 경로 생성 — custom_score 낮은(평지) 엣지를 확률적으로 선호
        nodes = self._utils.circular_random_walk(start, self._inp.target_km or 3.0)

        # 경로가 없는 경우
        if not nodes:
            return WalkRouteResponse(
                status="FAILED",
                mode=self.mode,
                coordinates=[],
                total_km=0.0,
                fallback_reason=FallbackReason.NO_PATH,
            )

        pruned  = self._utils.prune_dead_ends(nodes)       # 왕복 가지 제거
        coords  = self._utils.extract_coordinates(pruned)  # [lat, lon] 좌표 목록
        total_m = self._utils.calc_distance(pruned)        # 총 이동 거리(미터)
        return WalkRouteResponse(
            status          = "SUCCESS" if coords else "FAILED",
            mode            = self.mode,
            coordinates     = coords,
            total_km        = round(total_m / 1000, 2),
            fallback_reason = None,
        )
