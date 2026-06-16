import networkx as nx

from src.route_engine.engines.oneway.random import oneway_random_route
from src.route_engine.engines.path_utils import find_nearest_node
from src.repository.layer.running_repository import RunningRepository

RUNNING_COURSE_TYPES = ["river", "park", "bike_track"]


def oneway_running_route(
    G: nx.Graph,
    start_lat: float,
    start_lon: float,
    dest_lat: float,
    dest_lon: float,
    target_m: float,
    radius_m: float,
    session,
) -> dict:
    courses = RunningRepository.get_running_layer_near(
        lat=start_lat,
        lon=start_lon,
        radius_m=radius_m,
        is_circular=False,
        course_types=RUNNING_COURSE_TYPES,
    )

    end_node = find_nearest_node(G, dest_lat, dest_lon)

    if not courses:
        start_node = find_nearest_node(G, start_lat, start_lon)
        result = oneway_random_route(G, start_node, end_node, target_m / 1000, weight="custom_score")
        result["mode"] = "oneway_running"
        result["matched_courses"] = []
        return result

    best_course = courses[0]
    start_node = find_nearest_node(G, best_course["start_lat"], best_course["start_lon"])
    result = oneway_random_route(G, start_node, end_node, target_m / 1000, weight="custom_score")
    result["mode"] = "oneway_running"
    result["matched_courses"] = courses
    return result
