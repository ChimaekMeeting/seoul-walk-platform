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


def _prune_metrics(gm: Optional[RouteGeometryMetrics]) -> dict:
    """PruneDiagnostics를 CSV 컬럼으로 편다(2026-09-10 노출). Beam solver도 이 함수를 쓴다.

    이 값들은 품질 판정이 아니라 튜닝 근거다 — 경유지는 순환 경로를 만들기 위한 내부
    수단이므로, 경유지가 잘려나갔다는 사실 자체는 해의 품질 미달이 아니다. 다만
    num_waypoints(N)를 올려도 실제로 지나는 경유지가 늘지 않는다면 그만큼 A* 호출이
    낭비이므로, N 기본값을 정할 때 이 값을 본다.

    waypoints_lost_clean(재통행 없는 구간에 휩쓸려 사라진 경유지) 대
    waypoints_lost_repeated(어떤 기준에서도 지워질 구간에서 사라진 경유지)의 비율은
    "겹침 제거 기준을 길이 기준에서 겹침 기준으로 바꿀 가치가 있는가"를 판단할 데이터다
    (PruneDiagnostics 클래스 docstring 참고).

    Route가 없어 진단을 못 만든 경우(prune_diagnostics=None)에는 빈 dict를 돌려
    해당 컬럼들이 None으로 남게 한다.
    """
    diagnostics = getattr(gm, "prune_diagnostics", None) if gm is not None else None
    if diagnostics is None:
        return {}
    return {
        "prune_branch_count": diagnostics.branch_count,
        "prune_branch_length_m": round(diagnostics.branch_length_m, 4),
        "prune_clean_branch_count": diagnostics.clean_branch_count,
        "prune_clean_branch_length_m": round(diagnostics.clean_branch_length_m, 4),
        "waypoints_lost_clean": diagnostics.waypoints_lost_clean,
        "waypoints_lost_repeated": diagnostics.waypoints_lost_repeated,
    }


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
        "num_waypoints_used": engine.config.num_waypoints,
        "effective_waypoints_used": gm.effective_waypoint_count,
        "pool_cache_hits": getattr(engine.last_pool_result, "cache_hits", None),
        "pool_cache_misses": getattr(engine.last_pool_result, "cache_misses", None),
        **_prune_metrics(gm),
    }


# 하이퍼파라미터 스윕용 정제 노브. GraspConfig에는 넣지 않는다 — 정제별 설정이라 모든
# 조합이 쓰지도 않는 노브를 들고 다니게 되므로, 정제 공통 주입구
# (WaypointEngine.refinement_options)로 보낸다. 여기 등록된 정제는
# waypoint_refinement.OPTIONS_AWARE_REFINEMENTS와 일치해야 한다 — 그렇지 않은 정제에
# 값을 실어 보내면 엔진 생성자가 ValueError로 막는다.
_REFINEMENT_PARAM_KEYS = {
    "alns": (  # ALNSConfig 필드 이름
        "iterations", "removal_fraction", "start_temperature_m", "cooling_rate",
        "segment_length", "reaction_factor", "candidate_limit", "max_cost_calls", "seed",
    ),
    "vns": ("max_shake_level",),
}


def _refinement_options_from_params(refinement: str, params: dict) -> Optional[dict]:
    """params의 <refinement>_* 키만 골라 정제가 아는 이름으로 되돌린다
    (ex) alns_iterations=60 → {"iterations": 60}, vns_max_shake_level=2 →
    {"max_shake_level": 2}). 하나도 없으면 None을 돌려 waypoint_refinement.py의 기본값을
    그대로 쓰게 한다."""
    keys = _REFINEMENT_PARAM_KEYS.get(refinement)
    if not keys:
        return None
    options = {key: params[f"{refinement}_{key}"] for key in keys if f"{refinement}_{key}" in params}
    return options or None


class CircularGraspWaypointLocalSolver(BasePathSolver):
    def __init__(self, name: str = "GRASP-Waypoint+Local", seed: int = _DEFAULT_SEED):
        super().__init__(name)
        self.seed = seed

    def solve(self, graph, start_node, target_node, params: dict) -> dict:
        target_km = params.get("target_km") or _DEFAULT_TARGET_KM
        seed = params.get("seed", self.seed)
        inp = CircularRouteInput(start_lat=0.0, start_lon=0.0, target_km=target_km)

        engine = CircularGraspWaypointLocalEngine(
            inp=inp, G=graph, mode="distance", seed=seed,
            num_waypoints=params.get("num_waypoints"),
        )
        path, cost = run_circular_engine_distance_only(engine, start_node, target_km)

        return {
            "paths": [path],
            "cost": cost,
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

        engine = CircularGraspWaypointVndEngine(
            inp=inp, G=graph, mode="distance", seed=seed,
            num_waypoints=params.get("num_waypoints"),
        )
        path, cost = run_circular_engine_distance_only(engine, start_node, target_km)

        return {
            "paths": [path],
            "cost": cost,
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

        engine = CircularGraspWaypointVnsEngine(
            inp=inp, G=graph, mode="distance", seed=seed,
            num_waypoints=params.get("num_waypoints"),
            vns_options=_refinement_options_from_params("vns", params),
        )
        path, cost = run_circular_engine_distance_only(engine, start_node, target_km)

        return {
            "paths": [path],
            "cost": cost,
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

        engine = CircularGraspWaypointAlnsEngine(
            inp=inp, G=graph, mode="distance", seed=seed,
            num_waypoints=params.get("num_waypoints"),
            alns_options=_refinement_options_from_params("alns", params),
        )
        path, cost = run_circular_engine_distance_only(engine, start_node, target_km)

        return {
            "paths": [path],
            "cost": cost,
            "astar_calls": engine.cost_cache.astar_calls,
            "cache_hits": engine.cost_cache.cache_hits,
            # destroy/repair operator 사용 횟수 등(요청서 §4.4/§7) — 다른 solver는 이 키를
            # 주지 않으므로 CSV에서는 이 알고리즘 행에만 채워지고 나머지는 None이다.
            "alns_operator_stats": json.dumps(engine.last_alns_stats) if engine.last_alns_stats else None,
            **_segment_metrics(engine, start_node, target_km),
        }
