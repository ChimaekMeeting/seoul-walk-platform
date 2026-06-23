from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.profiles import get_profile
from src.interfaces.schema.walk_schema import CircularMode, FallbackReason, WalkRouteResponse
from src.schema.route_schema import CircularRouteInput
from src.route_engine.scoring.scoring_engine import calculate_custom_score
from typing import Optional
from src.schema.route_schema import Weights

import networkx as nx

class CircularChildEngine:
    def __init__(
            self, inp: CircularRouteInput, G: nx.Graph, 
            mode: CircularMode = CircularMode.CHILD, 
            candidate_count: int = 5, 
            corridor_radius_m: float = 250.0, 
            custom_weights: Optional[Weights] = None
            ):
        self._inp              = inp
        self._G                = G.copy()  # 원본 그래프 보호
        self._utils            = PathUtils(self._G)
        self.mode              = mode
        profile                = get_profile("child")
        self._weights          = custom_weights or profile.weights
        self._blocked_tags     = profile.blocked_tags
        self._candidate_count  = candidate_count
        self._corridor_radius  = corridor_radius_m
        self.child_index: float = 0.0   # run() 이후 접근 가능
        self.child_profile: dict = {}   # run() 이후 접근 가능

    def run(self) -> WalkRouteResponse:
        """
        어린이 친화 점수를 반영한 순환 경로를 생성합니다.
        """
        # 엣지별 custom_score 기록 (in-place)
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
                status="FAILED", mode=self.mode,
                coordinates=[], total_km=0.0,
                fallback_reason=FallbackReason.NO_NEAREST_START_NODE,
            )

        best: dict | None = None
        for _ in range(self._candidate_count):
            nodes   = self._utils.circular_random_walk(start, self._inp.target_km or 3.0)
            pruned  = self._utils.prune_dead_ends(nodes)
            coords  = self._utils.extract_coordinates(pruned)
            total_m = self._calc_distance(pruned)

            candidate = self._annotate(coords, places)
            candidate.update({"nodes": pruned, "total_m": total_m})

            if best is None or candidate["child_index"] > best["child_index"]:
                best = candidate

        if best is None or not best.get("nodes"):
            return WalkRouteResponse(
                status="FAILED", mode=self.mode,
                coordinates=[], total_km=0.0,
                fallback_reason=FallbackReason.NO_PATH,
            )

        self.child_index   = best["child_index"]
        self.child_profile = best["child_profile"]
        coords             = best["coords"]
        return WalkRouteResponse(
            status          = "SUCCESS" if coords else "FAILED",
            mode            = self.mode,
            coordinates     = coords,
            total_km        = round(total_m / 1000, 2),
            fallback_reason = None,
        )

    def _annotate(self, coords: list[list[float]], places: list[dict]) -> dict:
        """
        경로 주변 어린이 장소를 분석하고 child_index를 계산합니다.
        """
        nearby = []
        for p in places:
            if p.get("lat") is None or p.get("lon") is None:
                continue
            # 리스트 컴프리헨션에서 필터와 값 계산에 _min_dist를 중복 호출하던 것을 1회로 통합
            d = self._min_dist(coords, p["lat"], p["lon"])
            if d <= self._corridor_radius:
                nearby.append({**p, "distance_m": round(d, 1)})
        protection  = sum(1 for p in nearby if p.get("category") == "어린이보호구역")
        play        = sum(1 for p in nearby if p.get("category") == "어린이놀이시설")
        child_index = round(min(10.0, 3.0 + protection * 1.2 + play * 1.5), 1)

        return {
            "coords":        coords,
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

