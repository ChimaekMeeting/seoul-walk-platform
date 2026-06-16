from src.route_engine.engines.path_utils import PathUtils


def annotate_child_friendliness(
    route: dict,
    child_places: list[dict],
    corridor_radius_m: float = 250.0,
) -> dict:
    coordinates = route.get("coordinates") or []

    nearby = []
    for place in child_places:
        lat, lon = place.get("lat"), place.get("lon")
        if lat is None or lon is None:
            continue
        distance_m = _min_distance_to_route_m(coordinates, lat, lon)
        if distance_m <= corridor_radius_m:
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
        "corridor_radius_m": corridor_radius_m,
    }
    return route


def _min_distance_to_route_m(coordinates: list, lat: float, lon: float) -> float:
    if not coordinates:
        return float("inf")
    return min(PathUtils.haversine_m(lat, lon, float(p[0]), float(p[1])) for p in coordinates)
