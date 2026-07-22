"""
benchmarks/solvers/grasp_solver.py

src/route_engine/engines/circular_grasp.py (GRASP + VNS)를 BasePathSolver 규격으로
감싸는 어댑터.
"""

from benchmarks.solvers._circular_engine_common import run_circular_engine
from benchmarks.solvers.base_solver import BasePathSolver
from src.route_engine.engines.circular_grasp import CircularGraspEngine
from src.schema.route_schema import CircularRouteInput

_DEFAULT_TARGET_KM = 3.0
_DEFAULT_SEED = 42


class GraspSolver(BasePathSolver):
    def __init__(self, name: str = "GRASP+VNS", seed: int = _DEFAULT_SEED):
        super().__init__(name)
        self.seed = seed

    def solve(self, graph, start_node, target_node, params: dict) -> dict:
        target_km = params.get("target_km") or _DEFAULT_TARGET_KM
        inp = CircularRouteInput(start_lat=0.0, start_lon=0.0, target_km=target_km)

        engine = CircularGraspEngine(
            inp=inp,
            G=graph,
            custom_weights=params.get("custom_weights"),
            profile=params.get("profile"),
            seed=self.seed,
        )
        path, cost = run_circular_engine(engine, start_node, target_km)

        return {"paths": [path], "cost": cost, "overlap_ratio": 0.0}
