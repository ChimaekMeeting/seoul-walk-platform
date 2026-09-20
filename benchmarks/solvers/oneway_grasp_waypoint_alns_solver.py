"""실제 OnewayGraspWaypointAlnsEngine을 벤치마크 규격으로 감싼 어댑터.

서비스의 ``oneway_random``과 같은 GRASP+ALNS 편도 엔진을 사용한다. 반환 경로는
엔진의 ``run()`` 응답과 동일하게 ``prune_dead_ends()``를 거친 뒤 하네스에 넘긴다.
후보 3개는 서비스 응답에는 포함되지만, 편도 후보 간 중첩 지표는 이번 벤치마크 범위
밖이므로 최종 경로 하나만 품질 지표의 대상으로 삼는다.
"""

import json

from benchmarks.solvers._oneway_engine_common import baseline_shortest_metrics
from benchmarks.solvers.base_solver import BasePathSolver
from benchmarks.solvers.grasp_waypoint_solver import (
    _grasp_config_from_params,
    _refinement_options_from_params,
)
from src.route_engine.engines.circular_grasp_waypoint_alns import GRASP_ALNS_CONFIG
from src.route_engine.engines.oneway_grasp_waypoint_alns import OnewayGraspWaypointAlnsEngine
from src.schema.route_schema import OnewayRouteInput

_DEFAULT_TARGET_KM = 3.0
_DEFAULT_SEED = 42


class OnewayGraspWaypointAlnsSolver(BasePathSolver):
    """편도 우회용 GRASP+ALNS를 공통 벤치마크 인터페이스에 연결한다."""

    def __init__(self, name: str = "GRASP-Waypoint+ALNS(oneway)", seed: int = _DEFAULT_SEED):
        super().__init__(name)
        self.seed = seed

    def solve(self, graph, start_node, target_node, params: dict) -> dict:
        target_km = params.get("target_km") or _DEFAULT_TARGET_KM
        seed = params.get("seed", self.seed)
        inp = OnewayRouteInput(
            start_lat=0.0, start_lon=0.0, end_lat=0.0, end_lon=0.0, target_km=target_km,
        )
        engine = OnewayGraspWaypointAlnsEngine(
            inp=inp,
            G=graph,
            mode="distance",
            seed=seed,
            num_waypoints=params.get("num_waypoints"),
            config=_grasp_config_from_params(params, base=GRASP_ALNS_CONFIG),
            alns_options=_refinement_options_from_params("alns", params),
            cost_context=params.get("cost_context"),
        )

        nodes = engine.find_path(start_node, target_km, end_node=target_node)
        if not nodes or len(nodes) < 2:
            raise ValueError("경로 생성 실패: 유효한 편도 우회 경로를 찾지 못했습니다 (NO_PATH)")

        # WaypointEngine.run()이 실제 사용자 응답을 만들 때와 같은 경로 정규화다.
        path = engine.utils.prune_dead_ends(nodes)
        if len(path) < 2:
            raise ValueError("경로 생성 실패: 잔가지 제거 후 남은 편도 경로가 없습니다")

        baseline = baseline_shortest_metrics(engine, path, start_node, target_node)
        baseline_km, baseline_overlap = baseline if baseline is not None else (None, None)
        pool = engine.last_pool_result
        route = engine.last_route
        return {
            "paths": [path],
            "cost": engine.utils.calc_distance(path),
            "baseline_shortest_km": baseline_km,
            "baseline_shortest_overlap_ratio": baseline_overlap,
            "astar_calls": engine.cost_cache.astar_calls,
            "cache_hits": engine.cost_cache.cache_hits,
            "pool_cache_hits": pool.cache_hits if pool is not None else None,
            "pool_cache_misses": pool.cache_misses if pool is not None else None,
            "selection_status": engine.last_selection_status,
            "feasible": engine.last_selection_status == "feasible",
            "num_waypoints_used": len(route.waypoints) if route is not None else None,
            "effective_waypoints_used": route.effective_waypoint_count if route is not None else None,
            "alns_operator_stats": json.dumps(engine.last_alns_stats) if engine.last_alns_stats else None,
        }
