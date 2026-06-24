import networkx as nx
import math, random
from typing import Optional

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.profiles import get_profile
from src.interfaces.schema.walk_schema import (
    WalkMode,
    WalkRouteStatus,
    WalkRouteResponse
)
from src.schema.route_schema import OnewayRouteInput, Weights
from src.route_engine.scoring.scoring_engine import calculate_custom_score


class OnewayRandomEngine:
    def __init__(
        self,
        inp: OnewayRouteInput,
        G: nx.Graph,
        custom_weights: Optional[Weights] = None,
    ):
        self.inp          = inp
        self.G            = G.copy()  # 원본 그래프 보호
        self.utils        = PathUtils(self.G)
        self.mode         = WalkMode.ONEWAY_RANDOM
        profile           = get_profile("default")
        self.weights      = custom_weights or profile.weights
        self.blocked_tags = profile.blocked_tags

    def run(self) -> WalkRouteResponse:
        """
        우회 편도 경로를 생성합니다.
        """
        # 엣지별 custom_score 기록 (in-place)
        calculate_custom_score(self.G, {
            "mode": "general",
            "weights": self.weights,
            "blocked_tags": self.blocked_tags,
        })

        # 출발 노드와 도착 노드 탐색
        start = self.utils.find_nearest_node(self.inp.start_lat, self.inp.start_lon)  # 출발 노드
        end   = self.utils.find_nearest_node(self.inp.end_lat,   self.inp.end_lon)    # 도착 노드

        # 출발 노드가 없는 경우
        if start is None:
            return WalkRouteResponse(
                status=WalkRouteStatus.NO_NEAREST_START_NODE,
                mode=self.mode,
                coordinates=[],
                total_km=0.0,
            )
        
        # 도착 노드가 없는 경우
        if end is None:
            return WalkRouteResponse(
                status=WalkRouteStatus.NO_NEAREST_END_NODE,
                mode=self.mode,
                coordinates=[],
                total_km=0.0,
            )
        
        # 경로 생성
        nodes = self.find_path(start, end, self.inp.target_km or 3.0)

        # 경로가 없는 경우
        if not nodes:
            return WalkRouteResponse(
                status=WalkRouteStatus.NO_PATH,
                mode=self.mode,
                coordinates=[],
                total_km=0.0,
            )

        coords  = self.utils.extract_coordinates(nodes)  # [lat, lon] 좌표 목록
        total_m = self.utils.calc_distance(nodes)        # 총 이동 거리(m)
        
        return WalkRouteResponse(
            status          = WalkRouteStatus.SUCCESS if coords else WalkRouteStatus.NO_PATH,
            mode            = self.mode,
            coordinates     = coords,
            total_km        = round(total_m / 1000, 2),
        )
    
    def find_path(self, start: int, end: int, target_km: float = 3.0) -> list[int]:
        """
        경유 노드를 활용한 우회 편도 경로 노드 목록을 반환합니다.
        """
        target_m = target_km * 1000  # 목표 거리(미터)
        p1       = self.G.nodes[start]
        p2       = self.G.nodes[end]

        lon1, lat1 = p1.get("lon", 0), p1.get("lat", 0)
        lon2, lat2 = p2.get("lon", 0), p2.get("lat", 0)
        dx, dy     = lon2 - lon1, lat2 - lat1
        dist_se    = math.sqrt(dx ** 2 + dy ** 2)

        # 출발-도착 직선에 수직인 방향으로 중점을 offset하여 실제 우회 루프 유도
        # 기존 방식(직선거리 비율 필터만)은 직선 근처 노드가 선택되어 우회 효과 약함
        offset_deg = (target_km * 0.35) / 111.0
        if dist_se > 1e-9:
            side = random.choice([1, -1])
            px   = -dy / dist_se * side  # 수직 단위벡터 (90도 회전)
            py   =  dx / dist_se * side
        else:
            angle = random.uniform(0, 2 * math.pi)
            px, py = math.cos(angle), math.sin(angle)

        target_lon = (lon1 + lon2) / 2 + px * offset_deg
        target_lat = (lat1 + lat2) / 2 + py * offset_deg

        candidates = []
        for node, data in self.G.nodes(data=True):
            if node in (start, end):
                continue
            nlon, nlat = data.get("lon", 0), data.get("lat", 0)
            d1    = math.sqrt((nlon - lon1) ** 2 + (nlat - lat1) ** 2) * 111000
            d2    = math.sqrt((nlon - lon2) ** 2 + (nlat - lat2) ** 2) * 111000
            total = d1 + d2
            if target_m * 0.6 <= total <= target_m * 0.9:
                d_target = math.sqrt((nlon - target_lon) ** 2 + (nlat - target_lat) ** 2)
                candidates.append((node, d_target))

        if not candidates:
            waypoint = self.utils.find_nearest_node(target_lat, target_lon)
        else:
            candidates.sort(key=lambda x: x[1])
            waypoint = random.choice(candidates[:5])[0]  # 상위 5개 중 랜덤 선택

        try:
            path1       = nx.shortest_path(self.G, start, waypoint, weight="custom_score")
            path1_edges = set(zip(path1[:-1], path1[1:]))

            # G 엣지를 직접 수정하지 않고 클로저로 페널티 적용 → 그래프 오염 방지
            def penalized_weight(u, v, data):
                base = data.get("custom_score", 1.0)
                return base * 100.0 if (u, v) in path1_edges or (v, u) in path1_edges else base

            path2 = nx.shortest_path(self.G, waypoint, end, weight=penalized_weight)
            return path1[:-1] + path2

        except Exception:
            try:
                return nx.shortest_path(self.G, start, end, weight="custom_score")  # 경유 실패 시 직선 최단 경로
            except Exception:
                return []
