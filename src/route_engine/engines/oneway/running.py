import math
import time
from typing import Optional

import networkx as nx

from src.interfaces.schema.running_schema import CourseInfo, OnewayRunningResponse
from src.repository.layer.running_repository import RunningRepository
from src.repository.network.graph_repository import GraphRepository
from src.route_engine.engines.oneway.dijkstra import dijkstra_route
from src.route_engine.engines.oneway.random import oneway_random_route
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


def oneway_running_route(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    target_km: Optional[float] = None,
    use_random: bool = True,
    radius_m: float = 5_000,
    G: Optional[nx.Graph] = None,
) -> OnewayRunningResponse:
    t0 = time.time()

    matched_courses = RunningRepository.get_running_layer_near(
        lat=start_lat, lon=start_lon, radius_m=radius_m, course_types=RUNNING_COURSE_TYPES, limit=5,
    )
    courses = [CourseInfo(**c) for c in matched_courses]
    print(f"[running/oneway] DB 코스 {len(courses)}건 ({time.time()-t0:.2f}s)")

    straight_m = math.sqrt((start_lat - end_lat) ** 2 + (start_lon - end_lon) ** 2) * 111_000
    graph_radius = max(straight_m * 1.5, 3_000)

    if G is None:
        mid_lat = (start_lat + end_lat) / 2
        mid_lon = (start_lon + end_lon) / 2
        G = GraphRepository.load_graph_near(mid_lat, mid_lon, radius_m=graph_radius)

    if G.number_of_nodes() == 0:
        return OnewayRunningResponse(
            mode="oneway_running", coordinates=[], total_distance_km=0.0,
            matched_courses=courses, error="해당 위치 주변에 경로 데이터가 없습니다.",
        )

    invalid = [n for n, d in G.nodes(data=True) if "lon" not in d or "lat" not in d]
    if invalid:
        G = G.copy()
        G.remove_nodes_from(invalid)

    if G.number_of_nodes() == 0:
        return OnewayRunningResponse(
            mode="oneway_running", coordinates=[], total_distance_km=0.0,
            matched_courses=courses, error="유효한 노드가 없습니다.",
        )

    G = _apply_weights(G)
    start_node = find_nearest_node(G, start_lat, start_lon)
    end_node   = find_nearest_node(G, end_lat, end_lon)

    if use_random and target_km:
        raw        = oneway_random_route(G, start_node, end_node, target_km, weight="custom_score")
        mode_label = "oneway_running_random"
    else:
        raw        = dijkstra_route(G, start_node, end_node, weight="custom_score")
        mode_label = "oneway_running_shortest"

    pruned = prune_dead_ends(raw["nodes"], G, max_branch_length=300)
    coords = extract_coordinates(G, pruned)
    total_m = sum(
        (G.get_edge_data(pruned[i], pruned[i + 1]) or {}).get("length", 0)
        for i in range(len(pruned) - 1)
    )
    print(f"[running/oneway] 완료 {time.time()-t0:.2f}s")
    return OnewayRunningResponse(
        mode=mode_label,
        coordinates=coords,
        total_distance_km=round(total_m / 1000, 2),
        matched_courses=courses,
    )
