import time

import networkx as nx

from src.interfaces.schema.running_schema import CourseInfo
from src.repository.layer.running_repository import RunningRepository
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.profiles import get_profile
from src.route_engine.schema import CircularRouteInput, FallbackReason, RouteOutput
from src.route_engine.scoring.scoring_engine import calculate_custom_score

RUNNING_COURSE_TYPES = ["river", "park", "bike_track", "trail"]


class CircularRunningEngine:
    def __init__(
        self,
        inp: CircularRouteInput,
        G: nx.Graph,
        profile_name: str = "running",
    ):
        self._inp          = inp
        self._G            = G.copy()         # 원본 그래프 보호
        self._utils        = PathUtils(self._G)
        profile            = get_profile(profile_name)
        self._weights      = profile.weights
        self._blocked_tags = profile.blocked_tags

    def run(self) -> RouteOutput:
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
            return RouteOutput(status="FAILED", mode="circular_running",
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_NEAREST_START_NODE)
        
        # 경로 생성
        nodes = self._utils.circular_random_walk(start, self._inp.target_km or 5.0)

        # 경로가 없는 경우
        if not nodes:
            return RouteOutput(status="FAILED", mode="circular_running",
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_PATH)

        pruned  = self._utils.prune_dead_ends(nodes, max_branch_length=300)  # 왕복 가지 제거
        coords  = self._utils.extract_coordinates(pruned)                    # [lat, lon] 좌표 목록
        total_m = self._utils.calc_distance(pruned)                          # 총 이동 거리(미터)
        return RouteOutput(
            status          = "SUCCESS" if coords else "FAILED",
            mode            = "circular_running",
            coordinates     = coords,
            total_km        = round(total_m / 1000, 2),
            fallback_reason = None,
        )