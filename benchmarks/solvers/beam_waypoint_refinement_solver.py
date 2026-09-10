"""
benchmarks/solvers/beam_waypoint_refinement_solver.py

Beam+{Local,VND,VNS,ALNS} 4종을 GRASP-Waypoint 4종·기존 Beam-Waypoint("beam-wp", 정제
없음)과 같은 조건·같은 CSV 스키마로 비교하기 위한 BasePathSolver 어댑터("Beam/GRASP
구축·정제 조립 분리" 이슈). waypoint_engine_assembly.py::WaypointEngine(
construction="beam", refinement=...)을 그대로 실행하며, 이미 grasp-wp-* solver가 쓰던
run_circular_engine_distance_only()/_segment_metrics() 헬퍼를 재사용해 같은 CSV
필드를 채운다.

기존 beam_waypoint_solver.py::CircularBeamWaypointSolver("beam-wp")는 건드리지
않았다 — 그 solver는 정제 단계가 아예 없는 "순수 Beam" 비교 기준으로 그대로 남겨두고,
이 파일이 정제를 추가한 4개 조합을 새 키("beam-wp-local"/"beam-wp-vnd"/"beam-wp-vns"/
"beam-wp-alns")로 별도 등록한다.
"""

import json

from benchmarks.solvers._circular_engine_common import run_circular_engine_distance_only
from benchmarks.solvers.base_solver import BasePathSolver
from benchmarks.solvers.grasp_waypoint_solver import _refinement_options_from_params, _segment_metrics
from src.route_engine.engines.grasp_waypoint_common import DEFAULT_CONFIG, GraspConfig
from src.route_engine.engines.waypoint_engine_assembly import WaypointEngine
from src.schema.route_schema import CircularRouteInput

_DEFAULT_TARGET_KM = 3.0
_DEFAULT_SEED = 42
_DEFAULT_BEAM_WIDTH = 8  # GraspConfig.rcl_size 기본값과 맞춘 "공정 비교" 기본값 —
# beam_construction()이 이 값을 Beam 탐색 폭이자 정제 단계의 이웃 폭으로 함께 쓴다
# (beam_waypoint_solver.py의 기존 관례와 동일).


class _BeamWaypointRefinementSolver(BasePathSolver):
    """refinement만 다른 4개 solver(Local/VND/VNS/ALNS)가 공유하는 실행 본문. 서브클래스는
    클래스 속성 `refinement`만 정하면 된다."""

    refinement: str = "local"

    def __init__(self, name: str, seed: int = _DEFAULT_SEED):
        super().__init__(name)
        self.seed = seed

    def solve(self, graph, start_node, target_node, params: dict) -> dict:
        target_km = params.get("target_km") or _DEFAULT_TARGET_KM
        seed = params.get("seed", self.seed)
        beam_width = params.get("beam_width", _DEFAULT_BEAM_WIDTH)
        config = GraspConfig(
            distance_tolerance_ratio=params.get(
                "distance_tolerance_ratio", DEFAULT_CONFIG.distance_tolerance_ratio,
            ),
            min_waypoint_separation_ratio=params.get(
                "min_waypoint_separation_ratio", DEFAULT_CONFIG.min_waypoint_separation_ratio,
            ),
            pairwise_cache_rows=params.get("pairwise_cache_rows", DEFAULT_CONFIG.pairwise_cache_rows),
            num_waypoints=params.get("num_waypoints", DEFAULT_CONFIG.num_waypoints),
            rcl_size=beam_width,
            angle_diversity_weight_m=params.get(
                "angle_diversity_weight_m", DEFAULT_CONFIG.angle_diversity_weight_m,
            ),
        )
        inp = CircularRouteInput(start_lat=0.0, start_lon=0.0, target_km=target_km)

        engine = WaypointEngine(
            inp=inp, G=graph, mode="distance", seed=seed, config=config,
            construction="beam", refinement=self.refinement,
            refinement_options=_refinement_options_from_params(self.refinement, params),
        )
        path, cost = run_circular_engine_distance_only(engine, start_node, target_km)

        result = {
            "paths": [path],
            "cost": cost,
            "astar_calls": engine.cost_cache.astar_calls,
            "cache_hits": engine.cost_cache.cache_hits,
            # num_waypoints_used/pool_cache_hits/pool_cache_misses는 아래 _segment_metrics()가
            # engine.config/engine.last_pool_result를 그대로 읽어 채운다(중복 안 함).
            **_segment_metrics(engine, start_node, target_km),
        }
        if self.refinement == "alns" and engine.last_alns_stats:
            result["alns_operator_stats"] = json.dumps(engine.last_alns_stats)
        return result


class CircularBeamWaypointLocalSolver(_BeamWaypointRefinementSolver):
    refinement = "local"

    def __init__(self, name: str = "Beam-Waypoint+Local", seed: int = _DEFAULT_SEED):
        super().__init__(name, seed)


class CircularBeamWaypointVndSolver(_BeamWaypointRefinementSolver):
    refinement = "vnd"

    def __init__(self, name: str = "Beam-Waypoint+VND", seed: int = _DEFAULT_SEED):
        super().__init__(name, seed)


class CircularBeamWaypointVnsSolver(_BeamWaypointRefinementSolver):
    refinement = "vns"

    def __init__(self, name: str = "Beam-Waypoint+VNS", seed: int = _DEFAULT_SEED):
        super().__init__(name, seed)


class CircularBeamWaypointAlnsSolver(_BeamWaypointRefinementSolver):
    refinement = "alns"

    def __init__(self, name: str = "Beam-Waypoint+ALNS", seed: int = _DEFAULT_SEED):
        super().__init__(name, seed)
