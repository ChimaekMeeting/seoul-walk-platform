import math
import time
from typing import Optional

import networkx as nx

from src.interfaces.schema.running_schema import CircularRunningResponse, CourseInfo
from src.repository.layer.running_repository import RunningRepository
from src.repository.network.graph_repository import GraphRepository
from src.route_engine.engines.circular.random import random_walk_route
from src.route_engine.engines.path_utils import extract_coordinates, find_nearest_node, prune_dead_ends

RUNNING_COURSE_TYPES = ["river", "park", "bike_track", "trail"]


def _apply_weights(G: nx.Graph, slope_weight: float = 0.5, running_weight: float = 1.0) -> nx.Graph:
    for u, v, data in G.edges(data=True):
        length  = data.get("length", 1.0) or 1.0
        safety  = data.get("safety_score", 0.5)
        nature  = data.get("nature_score", 0.5)
        slope   = data.get("slope_score", 0.5)
        running = data.get("running_score", 0.0)

        running_bonus = 1.0 + running * running_weight
        slope_factor  = 1.0 + slope * slope_weight
        length_bonus  = 1.0 + math.log1p(length / 50.0)

        G[u][v]["custom_score"] = (length * slope_factor) / (
            (safety + 1e-6) * (nature + 1e-6) * running_bonus * length_bonus
        )
    return G


def circular_running_route(
    lat: float,
    lon: float,
    target_km: float = 5.0,
    radius_m: float = 5_000,
    G: Optional[nx.Graph] = None,
) -> CircularRunningResponse:
    t0 = time.time()

    matched_courses = RunningRepository.get_running_layer_near(
        lat=lat, lon=lon, radius_m=radius_m, course_types=RUNNING_COURSE_TYPES, limit=5,
    )
    courses = [CourseInfo(**c) for c in matched_courses]
    print(f"[running/circular] DB 코스 {len(courses)}건 ({time.time()-t0:.2f}s)")

    graph_radius = target_km * 1000 * 2.5
    if G is None:
        G = GraphRepository.load_graph_near(lat, lon, radius_m=graph_radius)

    if G.number_of_nodes() == 0:
        return CircularRunningResponse(
            mode="circular_running", coordinates=[], total_distance_km=0.0,
            matched_courses=courses, error="해당 위치 주변에 경로 데이터가 없습니다.",
        )

    invalid = [n for n, d in G.nodes(data=True) if "lon" not in d or "lat" not in d]
    if invalid:
        G = G.copy()
        G.remove_nodes_from(invalid)

    if G.number_of_nodes() == 0:
        return CircularRunningResponse(
            mode="circular_running", coordinates=[], total_distance_km=0.0,
            matched_courses=courses, error="유효한 노드가 없습니다.",
        )

    G = _apply_weights(G)
    start_node = find_nearest_node(G, lat, lon)
    raw = random_walk_route(G, start_node, target_km, weight="custom_score")

    pruned = prune_dead_ends(raw["nodes"], G, max_branch_length=300)
    coords = extract_coordinates(G, pruned)
    total_m = sum(
        (G.get_edge_data(pruned[i], pruned[i + 1]) or {}).get("length", 0)
        for i in range(len(pruned) - 1)
    )
    print(f"[running/circular] 완료 {time.time()-t0:.2f}s")
    return CircularRunningResponse(
        mode="circular_running",
        coordinates=coords,
        total_distance_km=round(total_m / 1000, 2),
        matched_courses=courses,
    )
