"""
benchmarks/solvers/grasp_waypoint_solver.py

circular_grasp_waypoint_{local,vnd,vns,alns}.py(경유지 선택 기반 GRASP 4종)를
BasePathSolver 규격으로 감싸는 어댑터. 기존 grasp_solver.py(circular_grasp.py용)와
circular_alns.py(완전히 다른 독립 구현)는 이 파일에서 수정하지 않는다 — 별도의 신규
비교 대상으로 나란히 등록될 뿐이다.

P2-P3 최소거리 안전장치 추가 이후(요청서 "P2-P3 최소거리와 추가 검증만 반영"), engine이
find_path() 실행 후 남기는 last_route/last_selection_status를 읽어 벤치마크 CSV에
d12/d23/d31, waypoint_separation_m, min_waypoint_separation_m, selection_status,
segment_balance_error를 추가로 기록한다(요청서 §6).

원형성 진단(요청서 "최종 경로가 실제로 원형에 가까운지", 2026-08-30) 추가 이후,
engine.find_path()가 이미 계산해 남겨두는 last_geometry_metrics(grasp_waypoint_common.py::
compute_route_geometry_metrics)를 그대로 옮겨 적는다 — 여기서 별도로 A*를 다시 부르거나
d12/d23/d31을 재계산하지 않는다(엔진과 벤치마크가 서로 다른 값을 낼 위험을 원천 차단).
"""

import json
from typing import Optional

from benchmarks.solvers._circular_engine_common import run_circular_engine_distance_only
from benchmarks.solvers.base_solver import BasePathSolver
from src.route_engine.engines.circular_grasp_waypoint_alns import CircularGraspWaypointAlnsEngine
from src.route_engine.engines.circular_grasp_waypoint_local import CircularGraspWaypointLocalEngine
from src.route_engine.engines.circular_grasp_waypoint_vnd import CircularGraspWaypointVndEngine
from src.route_engine.engines.circular_grasp_waypoint_vns import CircularGraspWaypointVnsEngine
from src.route_engine.engines.grasp_waypoint_common import RouteGeometryMetrics
from src.schema.route_schema import CircularRouteInput

_DEFAULT_TARGET_KM = 3.0
_DEFAULT_SEED = 42


def _segment_metrics(engine, start_node: int, target_km: float) -> dict:
    status = getattr(engine, "last_selection_status", None)
    target_m = target_km * 1000
    min_separation_m = target_m * engine.config.min_waypoint_separation_ratio
    gm: Optional[RouteGeometryMetrics] = getattr(engine, "last_geometry_metrics", None)

    def r(value, digits=4):
        return round(value, digits) if value is not None else None

    if gm is None:
        gm = RouteGeometryMetrics(None, None, None, None, None, False)

    segments = gm.segment_lengths_m
    angles = gm.waypoint_angle_diffs_deg

    return {
        "selection_status": status,
        "feasible": status == "feasible",
        "segment_p1_p2_m": r(segments[0]) if segments else None,
        "segment_p2_p3_m": r(segments[1]) if segments and len(segments) > 1 else None,
        "segment_p3_p1_m": r(segments[-1]) if segments else None,
        "waypoint_separation_m": r(gm.waypoint_separation_m),
        "min_waypoint_separation_m": round(min_separation_m, 4),
        "repeated_edge_ratio": r(gm.repeated_edge_ratio, 4),
        "waypoint_angle_diff_deg": r(angles[0], 2) if angles else None,
        "segment_balance_ratio": r(gm.segment_balance_ratio, 4),
        "is_degenerate_loop": gm.is_degenerate_loop,
    }


class CircularGraspWaypointLocalSolver(BasePathSolver):
    def __init__(self, name: str = "GRASP-Waypoint+Local", seed: int = _DEFAULT_SEED):
        super().__init__(name)
        self.seed = seed

    def solve(self, graph, start_node, target_node, params: dict) -> dict:
        target_km = params.get("target_km") or _DEFAULT_TARGET_KM
        seed = params.get("seed", self.seed)
        inp = CircularRouteInput(start_lat=0.0, start_lon=0.0, target_km=target_km)

        engine = CircularGraspWaypointLocalEngine(inp=inp, G=graph, mode="distance", seed=seed)
        path, cost = run_circular_engine_distance_only(engine, start_node, target_km)

        return {
            "paths": [path],
            "cost": cost,
            "overlap_ratio": 0.0,
            "astar_calls": engine.cost_cache.astar_calls,
            "cache_hits": engine.cost_cache.cache_hits,
            **_segment_metrics(engine, start_node, target_km),
        }


class CircularGraspWaypointVndSolver(BasePathSolver):
    def __init__(self, name: str = "GRASP-Waypoint+VND", seed: int = _DEFAULT_SEED):
        super().__init__(name)
        self.seed = seed

    def solve(self, graph, start_node, target_node, params: dict) -> dict:
        target_km = params.get("target_km") or _DEFAULT_TARGET_KM
        seed = params.get("seed", self.seed)
        inp = CircularRouteInput(start_lat=0.0, start_lon=0.0, target_km=target_km)

        engine = CircularGraspWaypointVndEngine(inp=inp, G=graph, mode="distance", seed=seed)
        path, cost = run_circular_engine_distance_only(engine, start_node, target_km)

        return {
            "paths": [path],
            "cost": cost,
            "overlap_ratio": 0.0,
            "astar_calls": engine.cost_cache.astar_calls,
            "cache_hits": engine.cost_cache.cache_hits,
            **_segment_metrics(engine, start_node, target_km),
        }


class CircularGraspWaypointVnsSolver(BasePathSolver):
    def __init__(self, name: str = "GRASP-Waypoint+VNS", seed: int = _DEFAULT_SEED):
        super().__init__(name)
        self.seed = seed

    def solve(self, graph, start_node, target_node, params: dict) -> dict:
        target_km = params.get("target_km") or _DEFAULT_TARGET_KM
        seed = params.get("seed", self.seed)
        inp = CircularRouteInput(start_lat=0.0, start_lon=0.0, target_km=target_km)

        engine = CircularGraspWaypointVnsEngine(inp=inp, G=graph, mode="distance", seed=seed)
        path, cost = run_circular_engine_distance_only(engine, start_node, target_km)

        return {
            "paths": [path],
            "cost": cost,
            "overlap_ratio": 0.0,
            "astar_calls": engine.cost_cache.astar_calls,
            "cache_hits": engine.cost_cache.cache_hits,
            **_segment_metrics(engine, start_node, target_km),
        }


class CircularGraspWaypointAlnsSolver(BasePathSolver):
    def __init__(self, name: str = "GRASP-Waypoint+ALNS", seed: int = _DEFAULT_SEED):
        super().__init__(name)
        self.seed = seed

    def solve(self, graph, start_node, target_node, params: dict) -> dict:
        target_km = params.get("target_km") or _DEFAULT_TARGET_KM
        seed = params.get("seed", self.seed)
        inp = CircularRouteInput(start_lat=0.0, start_lon=0.0, target_km=target_km)

        engine = CircularGraspWaypointAlnsEngine(inp=inp, G=graph, mode="distance", seed=seed)
        path, cost = run_circular_engine_distance_only(engine, start_node, target_km)

        return {
            "paths": [path],
            "cost": cost,
            "overlap_ratio": 0.0,
            "astar_calls": engine.cost_cache.astar_calls,
            "cache_hits": engine.cost_cache.cache_hits,
            # destroy/repair operator 사용 횟수 등(요청서 §4.4/§7) — 다른 solver는 이 키를
            # 주지 않으므로 CSV에서는 이 알고리즘 행에만 채워지고 나머지는 None이다.
            "alns_operator_stats": json.dumps(engine.last_alns_stats) if engine.last_alns_stats else None,
            **_segment_metrics(engine, start_node, target_km),
        }
