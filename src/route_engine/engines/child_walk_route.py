import math

import networkx as nx

from src.interfaces.schema.prewalk_schema import Weights
from src.repository.layer.child_repository import ChildRepository
from src.route_engine.features import build_child_weights
from src.service.route.route_service import RouteService


class ChildWalkRoute:
    def __init__(
        self,
        candidate_count: int = 5,
        corridor_radius_m: float = 250.0,
    ):
        self._candidate_count = candidate_count
        self._corridor_radius_m = corridor_radius_m
        self._route_service = RouteService()

    def get_route(
        self,
        context: dict,
        weights: Weights | None = None,
        G_full: nx.Graph | None = None,
    ) -> dict:
        child_weights = build_child_weights(weights)

        origin = context["origin"]["coordinate"]
        start_lat = float(origin["lat"])
        start_lon = float(origin["lon"])
        distance_km = float(context.get("distance_km", 3.0))
        search_radius_m = max(distance_km * 1000 * 1.5, 1500.0)

        places = ChildRepository.get_child_places_near(start_lat, start_lon, search_radius_m)

        attempts = max(
            1,
            self._candidate_count if context.get("mode", "circular") == "circular" else 1,
        )
        best_route: dict | None = None

        for _ in range(attempts):
            route = self._route_service.get_route(context, child_weights, G_full)
            if route.get("error"):
                return route

            route = self.annotate_child_friendliness(route, places)
            if best_route is None or route.get("child_index", 0) > best_route.get("child_index", 0):
                best_route = route

        return best_route or {
            "mode": context.get("mode", "circular"),
            "coordinates": [],
            "total_distance_km": 0.0,
            "error": "아이 동반 산책 경로를 계산하지 못했습니다",
        }

    def annotate_child_friendliness(
        self,
        route: dict,
        child_places: list[dict],
        *,
        corridor_radius_m: float | None = None,
    ) -> dict:
        radius = corridor_radius_m if corridor_radius_m is not None else self._corridor_radius_m
        coordinates = route.get("coordinates") or []

        nearby = []
        for place in child_places:
            lat, lon = place.get("lat"), place.get("lon")
            if lat is None or lon is None:
                continue
            distance_m = self._min_distance_to_route_m(coordinates, lat, lon)
            if distance_m <= radius:
                nearby.append({**place, "distance_m": round(distance_m, 1)})

        protection_count = sum(1 for p in nearby if p.get("category") == "어린이보호구역")
        play_count = sum(1 for p in nearby if p.get("category") == "어린이놀이시설")
        child_index = min(10.0, 3.0 + protection_count * 1.2 + play_count * 1.5)

        route["child_index"] = round(child_index, 1)
        route["child_profile"] = {
            "nearby_child_places": sorted(nearby, key=lambda x: x["distance_m"])[:10],
            "nearby_protection_zone_count": protection_count,
            "nearby_play_facility_count": play_count,
            "loaded_child_place_count": len(child_places),
            "corridor_radius_m": radius,
        }
        return route

    @staticmethod
    def _min_distance_to_route_m(
        coordinates: list[list[float]],
        lat: float,
        lon: float,
    ) -> float:
        if not coordinates:
            return float("inf")
        return min(_haversine_m(lat, lon, float(p[0]), float(p[1])) for p in coordinates)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))
