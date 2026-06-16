import math

import networkx as nx

from src.repository.layer.child_repository import ChildRepository
from src.route_engine.engines.circular.random import random_walk_route
from src.route_engine.engines.path_utils import extract_coordinates, find_nearest_node, prune_dead_ends
from src.route_engine.profiles import get_profile


def circular_child_route(
    G: nx.Graph,
    start_lat: float,
    start_lon: float,
    distance_km: float = 3.0,
    candidate_count: int = 5,
    corridor_radius_m: float = 250.0,
) -> dict:
    child_weights    = get_profile("child").weights
    search_radius_m  = max(distance_km * 1000 * 1.5, 1500.0)
    places           = ChildRepository.get_child_places_near(start_lat, start_lon, search_radius_m)

    _apply_weights(G, child_weights)
    start_node = find_nearest_node(G, start_lat, start_lon)

    best: dict | None = None
    for _ in range(candidate_count):
        raw   = random_walk_route(G, start_node, distance_km, weight="custom_score")
        nodes = prune_dead_ends(raw["nodes"], G)
        route = {
            "mode":               "circular_child",
            "coordinates":        extract_coordinates(G, nodes),
            "total_distance_km":  raw["total_distance_km"],
        }
        route = _annotate(route, places, corridor_radius_m)
        if best is None or route.get("child_index", 0) > best.get("child_index", 0):
            best = route

    return best or {
        "mode": "circular_child", "coordinates": [], "total_distance_km": 0.0,
        "error": "아이 동반 순환 경로를 계산하지 못했습니다.",
    }


def _apply_weights(G: nx.Graph, weights) -> None:
    for u, v, data in G.edges(data=True):
        length = data.get("length", 1.0) or 1.0
        safety = data.get("safety_score", 0.5)
        nature = data.get("nature_score", 0.5)
        slope  = data.get("slope_score", 0.5)
        child  = data.get("child_score", 0.0)

        slope_penalty = (2.0 - slope) ** weights.slope
        child_bonus   = 1.0 + child * weights.child
        G[u][v]["custom_score"] = (length * slope_penalty) / (
            (safety + 1e-6) ** weights.safety * (nature + 1e-6) ** weights.nature * child_bonus
        )


def _annotate(route: dict, places: list, corridor_radius_m: float) -> dict:
    coords = route.get("coordinates") or []
    nearby = [
        {**p, "distance_m": round(_min_dist(coords, p["lat"], p["lon"]), 1)}
        for p in places
        if p.get("lat") is not None and p.get("lon") is not None
        and _min_dist(coords, p["lat"], p["lon"]) <= corridor_radius_m
    ]
    protection = sum(1 for p in nearby if p.get("category") == "어린이보호구역")
    play       = sum(1 for p in nearby if p.get("category") == "어린이놀이시설")
    route["child_index"]   = round(min(10.0, 3.0 + protection * 1.2 + play * 1.5), 1)
    route["child_profile"] = {
        "nearby_child_places":            sorted(nearby, key=lambda x: x["distance_m"])[:10],
        "nearby_protection_zone_count":   protection,
        "nearby_play_facility_count":     play,
        "loaded_child_place_count":       len(places),
        "corridor_radius_m":              corridor_radius_m,
    }
    return route


def _min_dist(coordinates: list, lat: float, lon: float) -> float:
    if not coordinates:
        return float("inf")
    return min(_haversine(lat, lon, float(p[0]), float(p[1])) for p in coordinates)


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R   = 6371000.0
    p1  = math.radians(lat1)
    p2  = math.radians(lat2)
    dp  = math.radians(lat2 - lat1)
    dl  = math.radians(lon2 - lon1)
    a   = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))
