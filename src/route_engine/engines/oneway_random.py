import networkx as nx
import math
import random
from typing import Optional
import logging

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.profiles import ScoringProfile, get_profile, merge_weights
from src.interfaces.schema.walk_schema import (
    WalkMode,
    WalkRouteStatus,
    WalkRouteResponse
)
from src.schema.route_schema import OnewayRouteInput, Weights
from src.route_engine.scoring.scoring_engine import calculate_custom_score

logger = logging.getLogger(__name__)

class OnewayRandomEngine:
    def __init__(
        self,
        inp: OnewayRouteInput,
        G: nx.Graph,
        custom_weights: Optional[Weights] = None,
        profile: Optional[ScoringProfile] = None,
    ):
        self.inp           = inp
        self.G             = G.copy()  # 원본 그래프 보호
        self.utils         = PathUtils(self.G)
        self.mode          = WalkMode.ONEWAY_RANDOM
        profile_config     = get_profile(profile)
        self.weights       = merge_weights(profile_config.weights, custom_weights)
        self.blocked_tags  = profile_config.blocked_tags
        self.scoring_mode  = profile_config.scoring_mode

    def run(self) -> WalkRouteResponse:
        """
        우회 편도 경로를 생성합니다.
        """
        logger.info(f"랜덤 편도 경로 생성 엔진을 시작합니다: target_km={self.inp.target_km}, scoring_mode={self.scoring_mode}, weights={self.weights}")

        # 엣지별 custom_score 기록 (in-place)
        calculate_custom_score(self.G, {
            "mode": self.scoring_mode,
            "weights": self.weights,
            "blocked_tags": self.blocked_tags,
        })

        # 출발 노드와 도착 노드 탐색
        start = self.utils.find_nearest_node(self.inp.start_lat, self.inp.start_lon)  # 출발 노드
        end   = self.utils.find_nearest_node(self.inp.end_lat,   self.inp.end_lon)    # 도착 노드

        # 출발 노드가 없는 경우
        if start is None:
            logger.warning("출발 노드를 찾지 못했습니다.")
            return WalkRouteResponse(
                status=WalkRouteStatus.NO_NEAREST_START_NODE,
                mode=self.mode,
                coordinates=[],
                total_km=0.0,
            )
        
        # 도착 노드가 없는 경우
        if end is None:
            logger.warning("도착 노드를 찾지 못했습니다.")
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
            logger.warning("경로가 비어 있습니다.")
            return WalkRouteResponse(
                status=WalkRouteStatus.NO_PATH,
                mode=self.mode,
                coordinates=[],
                total_km=0.0,
            )

        pruned  = self.utils.prune_dead_ends(nodes)        # 왕복 가지 제거
        coords  = self.utils.extract_coordinates(pruned)  # [lat, lon] 좌표 목록
        total_m = self.utils.calc_distance(pruned)        # 총 이동 거리(m)
        total_km = round(total_m / 1000, 2)

        logger.info(f"total_km: {total_km}")
        
        return WalkRouteResponse(
            status          = WalkRouteStatus.SUCCESS if coords else WalkRouteStatus.NO_PATH,
            mode            = self.mode,
            coordinates     = coords,
            total_km        = total_km,
        )
    
    def find_path(self, start: int, end: int, target_km: float = 3.0) -> list[int]:
        """
        경유 노드를 활용한 우회 편도 경로 노드 목록을 반환합니다.
        여러 waypoint 후보로 실제 경로를 만들어보고, target_km과의 거리 오차가
        작은 상위 후보 중 하나를 무작위로 선택합니다(랜덤 편도 경로 특성 유지).
        """
        target_m = target_km * 1000  # 목표 거리(미터)

        try:
            shortest_path = nx.shortest_path(self.G, start, end, weight="custom_score")
        except Exception:
            logger.exception("최단 경로 생성에 실패했습니다.")
            return []

        # custom_score 기준 최단경로는 선호도가 반영되어 실제 최단거리와 다를 수 있으므로,
        # "이미 목표 거리 이상인지" 판단은 실제 거리(length) 기준 최단경로로 한다.
        try:
            shortest_by_length = nx.shortest_path(self.G, start, end, weight="length")
            min_dist_m         = self.utils.calc_distance(shortest_by_length)
        except Exception:
            min_dist_m = self.utils.calc_distance(shortest_path)

        # 실제로 도달 가능한 최소 거리가 이미 목표 거리 이상이면 우회할 필요가 없음
        if min_dist_m >= target_m:
            logger.info("최단 경로가 이미 목표 거리 이상이므로 최단 경로를 반환합니다.")
            return shortest_path

        candidates = []  # (오차, 경로) 목록
        for waypoint in self._select_waypoint_candidates(start, end, target_m):
            path = self._build_route_via_waypoint(start, waypoint, end)
            if path is None:
                continue
            diff = abs(self.utils.calc_distance(path) - target_m)
            candidates.append((diff, path))

        if candidates:
            return self._pick_from_top_candidates(candidates)

        logger.warning("우회 경로 생성에 실패했습니다. 최단 경로로 대체합니다.")
        return shortest_path

    def _pick_from_top_candidates(self, candidates: list[tuple[float, list[int]]], top_n: int = 3) -> list[int]:
        """
        목표 거리와의 오차가 작은 상위 top_n개 후보 중 하나를 무작위로 선택합니다.
        오차가 큰 후보는 후보군 자체에서 배제하여, 무작위성을 유지하면서도
        목표 거리에서 크게 벗어나는 경로는 선택되지 않도록 합니다.
        """
        candidates.sort(key=lambda c: c[0])
        top = candidates[:top_n]
        return random.choice(top)[1]

    def _select_waypoint_candidates(self, start: int, end: int, target_m: float, max_candidates: int = 5) -> list[int]:
        """
        출발-도착 직선에서 수직으로 offset된 지점들 주변의 waypoint 후보 목록을 반환합니다.
        기존 방식(직선거리 비율 필터만)은 직선 근처 노드가 선택되어 우회 효과 약함.
        """
        p1 = self.G.nodes[start]
        p2 = self.G.nodes[end]

        lon1, lat1 = p1.get("lon", 0), p1.get("lat", 0)
        lon2, lat2 = p2.get("lon", 0), p2.get("lat", 0)
        dx, dy     = lon2 - lon1, lat2 - lat1
        dist_se    = math.sqrt(dx ** 2 + dy ** 2)

        offset_deg = (target_m / 1000 * 0.35) / 111.0

        # 좌/우 양쪽 offset 지점을 모두 후보 타겟으로 사용 (편향 없이 더 넓게 탐색)
        targets = []
        if dist_se > 1e-9:
            px, py = -dy / dist_se, dx / dist_se  # 수직 단위벡터 (90도 회전)
            for side in (1, -1):
                targets.append((
                    (lon1 + lon2) / 2 + px * side * offset_deg,
                    (lat1 + lat2) / 2 + py * side * offset_deg,
                ))
        else:
            for angle in (0.0, math.pi):
                targets.append((
                    lon1 + math.cos(angle) * offset_deg,
                    lat1 + math.sin(angle) * offset_deg,
                ))

        scored = []
        for node, data in self.G.nodes(data=True):
            if node in (start, end):
                continue
            nlon, nlat = data.get("lon", 0), data.get("lat", 0)
            d1    = math.sqrt((nlon - lon1) ** 2 + (nlat - lat1) ** 2) * 111000
            d2    = math.sqrt((nlon - lon2) ** 2 + (nlat - lat2) ** 2) * 111000
            total = d1 + d2
            # 직선거리 합은 실제 도로 거리와 차이가 날 수 있으므로 넉넉하게 필터링하고,
            # 최종 후보 선택은 _build_route_via_waypoint로 만든 실제 경로 거리 기준으로 한다.
            if not (target_m * 0.4 <= total <= target_m * 1.2):
                continue
            d_target = min(
                math.sqrt((nlon - tlon) ** 2 + (nlat - tlat) ** 2)
                for tlon, tlat in targets
            )
            scored.append((node, d_target))

        scored.sort(key=lambda x: x[1])
        waypoints = [node for node, _ in scored[:max_candidates]]

        if not waypoints:
            tlon, tlat = targets[0]
            fallback = self.utils.find_nearest_node(tlat, tlon)
            if fallback is not None:
                waypoints = [fallback]

        return waypoints

    def _build_route_via_waypoint(self, start: int, waypoint: int, end: int) -> Optional[list[int]]:
        """
        start -> waypoint -> end 경로를 생성합니다. 실패 시 None을 반환합니다.
        """
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
            return None