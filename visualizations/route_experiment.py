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

from src.route_engine.alt_runtime import attach_alt_heuristic, prepare_alt_heuristic
from src.route_engine.engines import circular_beam, oneway_astar, oneway_beam
from src.route_engine.engines.path_utils import PathUtils, _TOLERANCE_RATIO
from src.schema.route_schema import CircularRouteInput, OnewayRouteInput
from visualizations.astar_adapter import record_astar_run
from visualizations.beam_adapter import record_beam_trace
from visualizations.route_trace import SearchTrace
from visualizations.waypoint_adapter import record_waypoint_trace

# A* 실행에 쓰는 ALT 기본값. 시각화는 src.config.settings를 import하지 않으므로
# 서비스 기본값(WALK_ALT_METHOD/K/SEED)과 같은지는 테스트가 대조한다.
DEFAULT_ALT_METHOD = "planar"
DEFAULT_ALT_K = 8
DEFAULT_ALT_SEED = 0
# 같은 A* 엔진을 서로 다른 휴리스틱으로 돌린 결과를 구분하는 이름이다.
SHORTEST_MODES = ("shortest", "shortest_alt")


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


def prepare_alt(graph, *, method, k, seed):
    """서비스와 같은 함수로 ALT 휴리스틱을 붙이고 준비 시간(초)을 돌려준다.

    서비스는 준비에 실패하면 Haversine으로 조용히 폴백하지만, 시각화는 그러면 안 된다
    — ALT라고 적힌 결과가 실제로는 Haversine 실행이면 비교가 거짓이 된다. 그래서
    여기서는 폴백을 허용하지 않고 중단한다.
    """
    started = perf_counter()
    heuristic, info = prepare_alt_heuristic(graph, enabled=True, method=method, k=k, seed=seed)
    if heuristic is None:
        raise RuntimeError(
            f"ALT 휴리스틱 준비에 실패했습니다(method={method}, k={k}). "
            "Haversine으로 조용히 폴백하면 비교가 잘못되므로 중단합니다."
        )
    attach_alt_heuristic(graph, heuristic, info)
    return perf_counter() - started


def execute(graph, mode, start, end, target_m=None, *, record=True, grasp_iterations=4, seed=42,
            heuristic="haversine", alt_method=DEFAULT_ALT_METHOD, alt_k=DEFAULT_ALT_K,
            alt_seed=DEFAULT_ALT_SEED, code_commit=None, artifact=None):
    # graph.graph의 feature cache까지 분리: 엔진의 얕은 copy만으로는 부족하다.
    local = copy.deepcopy(graph)
    fields = {"start_lat": start["lat"], "start_lon": start["lon"],
              "target_km": target_m / 1000 if target_m is not None else None}
    waypoint = mode.startswith("grasp_")
    shortest = mode in SHORTEST_MODES
    tolerance = _TOLERANCE_RATIO
    alt_prepare_seconds = None
    module = trace = None
    if waypoint:
        from src.route_engine.engines.grasp_waypoint_common import DEFAULT_CONFIG
        from src.route_engine.engines.waypoint_engine_assembly import WaypointEngine
        from visualizations.waypoint_trace import WaypointTrace
        config = replace(DEFAULT_CONFIG, grasp_iters=grasp_iterations)
        tolerance = config.distance_tolerance_ratio
        engine = WaypointEngine(CircularRouteInput(**fields), local, mode="distance", seed=seed,
                                config=config, construction="grasp", refinement=mode.split("_", 1)[1])
        trace = WaypointTrace(engine)
    elif mode == "circular":
        engine = circular_beam.CircularBeamEngine(CircularRouteInput(**fields), local)
        module = circular_beam
        trace = SearchTrace(engine)
    elif shortest:
        # 엔진은 서비스와 똑같이 그래프에 붙은 휴리스틱을 집어 쓴다. 준비 시간은
        # run_seconds에 섞지 않으려고 실행 구간 밖에서 따로 잰다.
        if heuristic not in ("haversine", "alt"):
            raise ValueError("heuristic은 'haversine' 또는 'alt'만 지원합니다.")
        if heuristic == "alt":
            alt_prepare_seconds = prepare_alt(local, method=alt_method, k=alt_k, seed=alt_seed)
        fields.update(end_lat=end["lat"], end_lon=end["lon"])
        engine = oneway_astar.OnewayAstarEngine(OnewayRouteInput(**fields), local)
    else:
        fields.update(end_lat=end["lat"], end_lon=end["lon"])
        engine = oneway_beam.OnewayBeamEngine(OnewayRouteInput(**fields), local)
        module = oneway_beam
        trace = SearchTrace(engine)
    paths = []
    original_prune = engine.utils.prune_dead_ends

    def capture_prune(nodes, *args, **kwargs):
        result = original_prune(nodes, *args, **kwargs)
        paths.append(list(result))
        return result

    recording = None
    with ExitStack() as stack:
        if not shortest:
            if not waypoint:
                stack.enter_context(patch.object(module, "calculate_custom_score", distance_score))
                stack.enter_context(patch.object(module, "compute_score_vector", distance_vector))
            stack.enter_context(patch.object(engine.utils, "prune_dead_ends", capture_prune))
            if record:
                stack.enter_context(trace)
        started = perf_counter()
        if shortest and record:
            # A*는 settrace 대신 "실제 실행 → 같은 조건 재생 → 노드열 대조"로 기록한다.
            recording = record_astar_run(
                engine, local, mode=mode, target_m=target_m, seed=seed,
                alt_seed=alt_seed if heuristic == "alt" else None,
                code_commit=code_commit, artifact=artifact,
                config={"heuristic": heuristic,
                        "alt_method": alt_method if heuristic == "alt" else None,
                        "alt_k": alt_k if heuristic == "alt" else None,
                        "alt_seed": alt_seed if heuristic == "alt" else None})
            responses = recording["responses"]
        else:
            responses = engine.run()
        elapsed = perf_counter() - started
    if shortest:
        paths = [list(engine.last_path_nodes)] if engine.last_path_nodes else []
    if record and not shortest:
        # settrace 산출물은 여기서 끝난다. 이 뒤의 파이프라인(route_story·route_view·화면)은
        # 어댑터가 낸 공통 이벤트만 본다.
        arguments = {"engine": engine, "mode": mode, "start_node": start["node"],
                     "end_node": end["node"], "paths": paths, "target_m": target_m,
                     "seed": seed, "code_commit": code_commit, "artifact": artifact}
        if waypoint:
            recording = record_waypoint_trace(
                trace, config={"heuristic": "haversine", "grasp_iters": config.grasp_iters,
                               "num_waypoints": config.num_waypoints,
                               "construction": engine.construction,
                               "refinement": engine.refinement},
                **arguments)
        else:
            recording = record_beam_trace(
                trace, config={"heuristic": "haversine"}, **arguments)
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
              "trace": recording["events"] if recording else (trace.events if trace else []),
              # 큐 추출 수는 A* 어댑터만 낸다. Beam·GRASP 기록에는 없다.
              "astar_queue_pops": (recording or {}).get("popped", trace.pops if trace else 0),
              "beam_iterations": trace.iterations if trace else 0,
              "trace_source_hashes": trace.source_hashes if trace else {},
              "conditions": recording["conditions"].as_dict() if recording else None}
    result["tolerance_ratio"] = tolerance
    result["run_seconds"] = elapsed if not record else None
    result["alt_prepare_seconds"] = alt_prepare_seconds
    if waypoint:
        result.update(config=asdict(config), seed=seed, refinement=engine.refinement,
                      engine=("GRASP · 구축만" if engine.refinement == "none" else f"GRASP + {engine.refinement.upper()}"), alns_stats=engine.last_alns_stats,
                      candidate_states_seen=trace.candidates_seen,
                      effective_waypoints=(engine.last_route.effective_waypoint_count if engine.last_route else 0))
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
