import math

import networkx as nx

from src.repository.layer.child_repository import ChildRepository
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.profiles import get_profile
from src.route_engine.schema import FallbackReason, OnewayRouteInput, RouteOutput
from src.route_engine.scoring.scoring_engine import calculate_custom_score


class OnewayChildEngine:
    def __init__(self, inp: OnewayRouteInput, G: nx.Graph, profile_name: str = "child", use_random: bool = True, corridor_radius_m: float = 250.0):
        self._inp             = inp
        self._G               = G.copy()  # 원본 그래프 보호
        self._utils           = PathUtils(self._G)
        profile               = get_profile(profile_name)
        self._weights         = profile.weights
        self._blocked_tags    = profile.blocked_tags
        self._use_random      = use_random
        self._corridor_radius = corridor_radius_m
        self.child_index: float = 0.0   # run() 이후 접근 가능
        self.child_profile: dict = {}   # run() 이후 접근 가능

    def run(self) -> RouteOutput:
        """
        어린이 친화 지수를 반영한 편도 경로를 생성합니다.
        """
        search_radius = max((self._inp.target_km or 3.0) * 1000 * 1.5, 1500.0)
        places        = ChildRepository.get_child_places_near(
            self._inp.start_lat, self._inp.start_lon, search_radius
        )

        calculate_custom_score(self._G, {
            "mode": "general",
            "weights": self._weights,
            "blocked_tags": self._blocked_tags,
        })

        start = self._utils.find_nearest_node(self._inp.start_lat, self._inp.start_lon)
        end   = self._utils.find_nearest_node(self._inp.end_lat,   self._inp.end_lon)

        if start is None:
            return RouteOutput(status="FAILED", mode="oneway_child",
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_NEAREST_START_NODE)
        if end is None:
            return RouteOutput(status="FAILED", mode="oneway_child",
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_NEAREST_END_NODE)

        nodes, mode_label = self._generate_route(start, end)
        if not nodes:
            return RouteOutput(status="FAILED", mode="oneway_child",
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_PATH)

        pruned  = self._utils.prune_dead_ends(nodes)
        coords  = self._utils.extract_coordinates(pruned)
        total_m = self._calc_distance(pruned)

        annotated          = self._annotate(coords, places)
        self.child_index   = annotated["child_index"]
        self.child_profile = annotated["child_profile"]

        return RouteOutput(
            status          = "SUCCESS" if coords else "FAILED",
            mode            = mode_label,
            coordinates     = coords,
            total_km        = round(total_m / 1000, 2),
            fallback_reason = None,
        )

    def _generate_route(self, start: int, end: int) -> tuple[list[int], str]:
        """
        use_random 여부에 따라 우회 또는 최단 경로를 생성합니다.
        """
        if self._use_random and self._inp.target_km:
            nodes = self._utils.oneway_waypoint_path(start, end, self._inp.target_km)
            label = "oneway_child_random"
        else:
            try:
                nodes = nx.shortest_path(self._G, start, end, weight="custom_score")
            except Exception:
                nodes = []
            label = "oneway_child_shortest"
        return nodes, label

    def _annotate(self, coords: list[list[float]], places: list[dict]) -> dict:
        """
        경로 주변 어린이 장소를 분석하고 child_index를 계산합니다.
        """
        nearby = [
            {**p, "distance_m": round(self._min_dist(coords, p["lat"], p["lon"]), 1)}
            for p in places
            if p.get("lat") is not None and p.get("lon") is not None
            and self._min_dist(coords, p["lat"], p["lon"]) <= self._corridor_radius
        ]
        protection  = sum(1 for p in nearby if p.get("category") == "어린이보호구역")
        play        = sum(1 for p in nearby if p.get("category") == "어린이놀이시설")
        child_index = round(min(10.0, 3.0 + protection * 1.2 + play * 1.5), 1)

        return {
            "child_index":   child_index,
            "child_profile": {
                "nearby_child_places":          sorted(nearby, key=lambda x: x["distance_m"])[:10],
                "nearby_protection_zone_count": protection,
                "nearby_play_facility_count":   play,
                "loaded_child_place_count":     len(places),
                "corridor_radius_m":            self._corridor_radius,
            },
        }

    def _min_dist(self, coords: list[list[float]], lat: float, lon: float) -> float:
        """
        경로상 임의의 점과 주어진 좌표 사이의 최소 거리(미터)를 반환합니다.
        """
        if not coords:
            return float("inf")
        return min(self._haversine(lat, lon, float(p[0]), float(p[1])) for p in coords)

    def _haversine(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        두 좌표 사이의 Haversine 거리(미터)를 반환합니다.
        """
        R  = 6371000.0
        p1 = math.radians(lat1)
        p2 = math.radians(lat2)
        dp = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a  = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _calc_distance(self, nodes: list[int]) -> float:
        """
        노드 목록의 총 이동 거리(미터)를 반환합니다.
        """
        return sum(
            (self._G.get_edge_data(nodes[i], nodes[i + 1]) or {}).get("length", 0)
            for i in range(len(nodes) - 1)
        )

