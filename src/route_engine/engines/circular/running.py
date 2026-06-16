import networkx as nx

from src.route_engine.engines.circular.random import random_walk_route
from src.route_engine.engines.path_utils import find_nearest_node
from src.repository.layer.running_repository import RunningRepository

RUNNING_COURSE_TYPES = ["river", "park", "bike_track"]


def circular_running_route(
    G: nx.Graph,
    start_lat: float,
    start_lon: float,
    target_m: float,
    radius_m: float,
    session,
) -> dict:
    courses = RunningRepository.get_running_layer_near(
        lat=start_lat,
        lon=start_lon,
        radius_m=radius_m,
        course_types=RUNNING_COURSE_TYPES,
    )

    start_node = find_nearest_node(G, start_lat, start_lon)

    if not courses:
        result = random_walk_route(G, start_node, target_m / 1000, weight="custom_score")
        result["mode"] = "circular_running"
        result["matched_courses"] = []
        return result

    result = random_walk_route(G, start_node, target_m / 1000, weight="custom_score")
    result["mode"] = "circular_running"
    result["matched_courses"] = courses
    return result
