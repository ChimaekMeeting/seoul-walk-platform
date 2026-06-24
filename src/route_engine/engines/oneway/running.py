import math
import time
from typing import Optional

import networkx as nx

from src.interfaces.schema.running_schema import CourseInfo, OnewayRunningResponse
from src.interfaces.schema.walk_schema import WalkRouteStatus, OnewayMode, WalkRouteResponse
from src.repository.layer.running_repository import RunningRepository
from src.repository.network.graph_repository import GraphRepository
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.profiles import get_profile
from src.schema.route_schema import OnewayRouteInput
from src.route_engine.scoring.scoring_engine import calculate_custom_score
from typing import Optional
from src.schema.route_schema import Weights

class OnewayRunningEngine:
    def __init__(self, inp: OnewayRouteInput, G: Optional[nx.Graph] = None, mode: OnewayMode = OnewayMode.RUNNING, custom_weights: Optional[Weights] = None):
        self._inp                     = inp
        self._G: nx.Graph | None      = G
        self._utils: PathUtils | None = None  # run() 이후 설정
        self.mode                     = mode
        profile                       = get_profile("running")
        self._weights                 = custom_weights or profile.weights
        self._blocked_tags            = profile.blocked_tags
        self.matched_courses: list[CourseInfo] = []  # run() 이후 접근 가능

    def run(self) -> WalkRouteResponse:
        """
        DB 코스 정보를 반영한 편도 런닝 경로를 생성합니다.
        """
        t0 = time.time()

        self.matched_courses = self._fetch_courses()
        self._G              = self._load_graph()

        if self._G.number_of_nodes() == 0:
            return WalkRouteResponse(status=WalkRouteStatus.NO_NEAREST_START_NODE, mode=self.mode,
                               coordinates=[], total_km=0.0)

        self._remove_invalid_nodes()

        if self._G.number_of_nodes() == 0:
            return WalkRouteResponse(status=WalkRouteStatus.NO_NEAREST_START_NODE, mode=self.mode,
                               coordinates=[], total_km=0.0)

        calculate_custom_score(self._G, {
            "mode": "running",
            "weights": self._weights,
            "blocked_tags": self._blocked_tags,
        })
        self._utils = PathUtils(self._G)

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

        nodes, _ = self._generate_route(start, end)
        if not nodes:
            return WalkRouteResponse(status=WalkRouteStatus.NO_PATH, mode=self.mode,
                               coordinates=[], total_km=0.0)

        print(f"[running/oneway] 완료 {time.time()-t0:.2f}s")
        pruned  = self._utils.prune_dead_ends(nodes, max_branch_length=300)
        coords  = self._utils.extract_coordinates(pruned)
        total_m = self._calc_distance(pruned)
        return WalkRouteResponse(
            status      = WalkRouteStatus.SUCCESS if coords else WalkRouteStatus.NO_PATH,
            mode        = self.mode,
            coordinates = coords,
            total_km    = round(total_m / 1000, 2),
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
        미리 로드된 그래프가 없으면 출발·도착 중간점 기준으로 DB에서 로드합니다.
        """
        if self._G is not None:
            # 다른 엔진과 달리 __init__에서 copy를 하지 않으므로 여기서 복사
            # 미복사 시 calculate_custom_score가 호출자의 원본 그래프를 오염시킴
            return self._G.copy()
        straight_m   = math.sqrt(
            (self._inp.start_lat - self._inp.end_lat) ** 2 +
            (self._inp.start_lon - self._inp.end_lon) ** 2
        ) * 111_000
        graph_radius = max(straight_m * 1.5, 3_000)  # 최소 3km 반경
        mid_lat      = (self._inp.start_lat + self._inp.end_lat) / 2
        mid_lon      = (self._inp.start_lon + self._inp.end_lon) / 2
        return GraphRepository.load_graph_near(mid_lat, mid_lon, radius_m=graph_radius)

    def _remove_invalid_nodes(self) -> None:
        """
        좌표 속성이 없는 노드를 그래프에서 제거합니다.
        """
        invalid = [n for n, d in self._G.nodes(data=True) if "lon" not in d or "lat" not in d]
        if invalid:
            self._G = self._G.copy()
            self._G.remove_nodes_from(invalid)

    def _generate_route(self, start: int, end: int) -> tuple[list[int], str]:
        """
        target_km 유무에 따라 우회 또는 최단 경로를 생성합니다.
        """
        if self._inp.target_km:
            nodes = self._utils.oneway_waypoint_path(start, end, self._inp.target_km)
            label = "oneway_running_random"
        else:
            try:
                nodes = nx.shortest_path(self._G, start, end, weight="custom_score")
            except Exception:
                nodes = []
            label = "oneway_running_shortest"
        return nodes, label

    def _calc_distance(self, nodes: list[int]) -> float:
        """
        노드 목록의 총 이동 거리(미터)를 반환합니다.
        """
        return sum(
            (self._G.get_edge_data(nodes[i], nodes[i + 1]) or {}).get("length", 0)
            for i in range(len(nodes) - 1)
        )

