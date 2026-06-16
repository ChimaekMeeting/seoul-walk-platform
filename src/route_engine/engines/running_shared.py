import networkx as nx

from src.route_engine.engines.path_utils import PathUtils

RUNNING_COURSE_TYPES = ["river", "park", "bike_track", "trail"]
RUNNING_TAGS = ["런닝"]


def _build_result(
    G: nx.Graph,
    nodes: list,
    mode: str,
    matched_courses: list[dict],
) -> dict:
    pruned = PathUtils.prune_dead_ends(nodes, G, max_branch_length=300)
    coords = PathUtils.extract_coordinates(G, pruned)
    total_m = PathUtils.path_distance_m(G, pruned)
    return {
        "mode": mode,
        "coordinates": coords,
        "total_distance_km": round(total_m / 1000, 2),
        "matched_courses": matched_courses,
    }
