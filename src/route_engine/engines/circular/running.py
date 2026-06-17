import time
from typing import Optional

import networkx as nx

from src.interfaces.schema.running_schema import CircularRunningResponse, CourseInfo
from src.repository.layer.running_repository import RunningRepository
from src.repository.network.graph_repository import GraphRepository
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.profiles import get_profile
from src.route_engine.schema import CircularRouteInput, FallbackReason, RouteOutput
from src.route_engine.scoring.scoring_engine import calculate_custom_score

RUNNING_COURSE_TYPES = ["river", "park", "bike_track", "trail"]


class CircularRunningEngine:
    def __init__(self, inp: CircularRouteInput, profile_name: str = "running", G: Optional[nx.Graph] = None):
        self._inp                     = inp
        self._G: nx.Graph | None      = G
        self._utils: PathUtils | None = None  # run() 이후 설정
        profile                       = get_profile(profile_name)
        self._weights                 = profile.weights
        self._blocked_tags            = profile.blocked_tags
        self.matched_courses: list[CourseInfo] = []  # run() 이후 접근 가능

    def run(self) -> RouteOutput:
        """
        DB 코스 정보를 반영한 순환 런닝 경로를 생성합니다.
        """
        t0 = time.time()

        self.matched_courses = self._fetch_courses()
        self._G              = self._load_graph()

        if self._G.number_of_nodes() == 0:
            return RouteOutput(status="FAILED", mode="circular_running",
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_GRAPH_DATA)

        self._remove_invalid_nodes()

        if self._G.number_of_nodes() == 0:
            return RouteOutput(status="FAILED", mode="circular_running",
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_GRAPH_DATA)

        calculate_custom_score(self._G, {
            "mode": "running",
            "weights": self._weights,
            "blocked_tags": self._blocked_tags,
        })
        self._utils = PathUtils(self._G)

        start = self._utils.find_nearest_node(self._inp.start_lat, self._inp.start_lon)
        if start is None:
            return RouteOutput(status="FAILED", mode="circular_running",
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_NEAREST_START_NODE)

        nodes = self._utils.circular_random_walk(start, self._inp.target_km or 5.0)
        if not nodes:
            return RouteOutput(status="FAILED", mode="circular_running",
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_PATH)

        print(f"[running/circular] 완료 {time.time()-t0:.2f}s")
        pruned  = self._utils.prune_dead_ends(nodes, max_branch_length=300)
        coords  = self._utils.extract_coordinates(pruned)
        total_m = self._calc_distance(pruned)
        return RouteOutput(
            status          = "SUCCESS" if coords else "FAILED",
            mode            = "circular_running",
            coordinates     = coords,
            total_km        = round(total_m / 1000, 2),
            fallback_reason = None,
        )

    def _fetch_courses(self) -> list[CourseInfo]:
        """
        DB에서 반경 내 런닝 코스 목록을 조회합니다.
        """
        raw = RunningRepository.get_running_layer_near(
            lat=self._inp.start_lat,
            lon=self._inp.start_lon,
            radius_m=5_000,
            course_types=RUNNING_COURSE_TYPES,
            limit=5,
        )
        return [CourseInfo(**c) for c in raw]

    def _load_graph(self) -> nx.Graph:
        """
        미리 로드된 그래프가 없으면 DB에서 로드합니다.
        """
        if self._G is not None:
            return self._G
        graph_radius = (self._inp.target_km or 5.0) * 1000 * 2.5  # 목표 거리의 2.5배 반경
        return GraphRepository.load_graph_near(
            self._inp.start_lat, self._inp.start_lon, radius_m=graph_radius
        )

    def _remove_invalid_nodes(self) -> None:
        """
        좌표 속성이 없는 노드를 그래프에서 제거합니다.
        """
        invalid = [n for n, d in self._G.nodes(data=True) if "lon" not in d or "lat" not in d]
        if invalid:
            self._G = self._G.copy()
            self._G.remove_nodes_from(invalid)

    def _calc_distance(self, nodes: list[int]) -> float:
        """
        노드 목록의 총 이동 거리(미터)를 반환합니다.
        """
        return sum(
            (self._G.get_edge_data(nodes[i], nodes[i + 1]) or {}).get("length", 0)
            for i in range(len(nodes) - 1)
        )

