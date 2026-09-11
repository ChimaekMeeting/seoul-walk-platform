"""기존 A*/Beam run()을 거리 기반 실험 조건으로 실행·검증한다."""

from __future__ import annotations

import copy
import hashlib
import math
import pickle
from contextlib import ExitStack
from dataclasses import asdict, replace
from unittest.mock import patch
from time import perf_counter

from src.route_engine.engines import circular_beam, oneway_astar, oneway_beam
from src.route_engine.engines.path_utils import PathUtils, _TOLERANCE_RATIO
from src.schema.route_schema import CircularRouteInput, OnewayRouteInput
from visualizations.route_trace import SearchTrace


def graph_digest(graph):
    """Graph의 lazy 뷰 캐시는 제외하고 실제 메타데이터·노드·엣지 속성을 비교한다."""
    contents = (graph.graph, list(graph.nodes(data=True)), list(graph.edges(data=True)))
    return hashlib.sha256(pickle.dumps(contents)).hexdigest()


def distance_score(graph, _profile):
    for _, _, data in graph.edges(data=True):
        data["custom_score"] = float(data["length"])
    return graph


def distance_vector(graph):
    # 선호 속성으로 후보 2·3을 고르는 영향도 제거한다.
    return {(u, v): {"distance": float(data["length"])}
            for a, b, data in graph.edges(data=True) for u, v in ((a, b), (b, a))}


def snap(graph, location):
    utils = PathUtils(graph)
    node = utils.find_nearest_node_with_expansion(location["lat"], location["lon"])
    if node is None:
        raise ValueError(f"{location.get('name', '입력점')}: 300m 안에 도보망 노드가 없습니다.")
    data = graph.nodes[node]
    return {"node": node, "lat": data["lat"], "lon": data["lon"],
            "distance_m": utils._haversine_m(location["lat"], location["lon"], data["lat"], data["lon"])}


def execute(graph, mode, start, end, target_m=None, *, record=True, grasp_iterations=4, seed=42):
    # graph.graph의 feature cache까지 분리: 엔진의 얕은 copy만으로는 부족하다.
    local = copy.deepcopy(graph)
    fields = {"start_lat": start["lat"], "start_lon": start["lon"],
              "target_km": target_m / 1000 if target_m is not None else None}
    waypoint = mode.startswith("grasp_")
    tolerance = _TOLERANCE_RATIO
    if waypoint:
        from src.route_engine.engines.grasp_waypoint_common import DEFAULT_CONFIG
        from src.route_engine.engines.waypoint_engine_assembly import WaypointEngine
        from visualizations.waypoint_trace import WaypointTrace
        config = replace(DEFAULT_CONFIG, grasp_iters=grasp_iterations)
        tolerance = config.distance_tolerance_ratio
        engine = WaypointEngine(CircularRouteInput(**fields), local, mode="distance", seed=seed,
                                config=config, construction="grasp", refinement=mode.split("_", 1)[1])
        module = None
    elif mode == "circular":
        engine = circular_beam.CircularBeamEngine(CircularRouteInput(**fields), local)
        module = circular_beam
    else:
        fields.update(end_lat=end["lat"], end_lon=end["lon"])
        module = oneway_astar if mode == "shortest" else oneway_beam
        cls = module.OnewayAstarEngine if mode == "shortest" else module.OnewayBeamEngine
        engine = cls(OnewayRouteInput(**fields), local)
    trace = WaypointTrace(engine) if waypoint else SearchTrace(engine, shortest=mode == "shortest")
    paths = []
    original_prune = engine.utils.prune_dead_ends

    def capture_prune(nodes, *args, **kwargs):
        result = original_prune(nodes, *args, **kwargs)
        paths.append(list(result))
        return result

    with ExitStack() as stack:
        if mode != "shortest":
            if not waypoint:
                stack.enter_context(patch.object(module, "calculate_custom_score", distance_score))
                stack.enter_context(patch.object(module, "compute_score_vector", distance_vector))
            stack.enter_context(patch.object(engine.utils, "prune_dead_ends", capture_prune))
        if record:
            stack.enter_context(trace)
        started = perf_counter()
        responses = engine.run()
        elapsed = perf_counter() - started
    if mode == "shortest":
        paths = [list(engine.last_path_nodes)] if engine.last_path_nodes else []
    metrics = []
    for nodes in paths:
        edges = list(zip(nodes, nodes[1:]))
        connected = len(nodes) > 1 and all(graph.has_edge(u, v) for u, v in edges)
        distance = sum(float(graph[u][v]["length"]) for u, v in edges) if connected else 0.0
        seen = set()
        repeated = 0.0
        for u, v in edges:
            key = frozenset((u, v))
            if key in seen:
                repeated += float(graph[u][v]["length"])
            seen.add(key)
        endpoints = bool(nodes) and nodes[0] == start["node"] and nodes[-1] == end["node"]
        error = abs(distance - target_m) if target_m is not None else None
        metrics.append({"distance_m": distance, "connected": connected, "endpoints_match": endpoints,
                        "target_error_m": error, "target_within_tolerance":
                        error <= target_m * tolerance if error is not None else None,
                        "repeated_edge_ratio": repeated / distance if distance else 0})
    result = {"mode": mode, "engine": type(engine).__name__, "target_m": target_m,
              "start": start, "end": end, "paths": paths, "metrics": metrics,
              "responses": [r.model_dump(mode="json") for r in responses],
              "trace": trace.events, "astar_queue_pops": trace.pops,
              "beam_iterations": trace.iterations, "trace_source_hashes": trace.source_hashes}
    result["tolerance_ratio"] = tolerance
    result["run_seconds"] = elapsed if not record else None
    if waypoint:
        result.update(config=asdict(config), seed=seed, refinement=engine.refinement,
                      engine=("GRASP · 구축만" if engine.refinement == "none" else f"GRASP + {engine.refinement.upper()}"), alns_stats=engine.last_alns_stats,
                      candidate_states_seen=trace.candidates_seen,
                      effective_waypoints=(engine.last_route.effective_waypoint_count if engine.last_route else 0))
    if record:
        result["trace"].append({"phase": "final", "paths": paths})
    return result


def compare_recording(recorded, plain):
    same = recorded["paths"] == plain["paths"] and recorded["responses"] == plain["responses"]
    if not same:
        raise RuntimeError("계측 전후 경로 결과가 달라졌습니다. 결과를 사용하지 마세요.")
    return True


def validate_lengths(graph):
    if graph.is_multigraph() or graph.is_directed():
        raise ValueError("현재 실험은 기존 무방향 단순 Graph를 대상으로 합니다.")
    for _, _, data in graph.edges(data=True):
        length = float(data.get("length", math.nan))
        if not math.isfinite(length) or length <= 0:
            raise ValueError("도보망에 양의 유한한 length가 없는 연결이 있습니다.")
