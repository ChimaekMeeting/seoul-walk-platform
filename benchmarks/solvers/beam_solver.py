"""
benchmarks/solvers/beam_solver.py

src/route_engine/engines/circular_beam.py (Beam Search)를 BasePathSolver 규격으로
감싸는 어댑터.
"""

from benchmarks.solvers._circular_engine_common import run_circular_engine
from benchmarks.solvers._oneway_engine_common import run_oneway_engine, base_shortest_path_overlap_ratio
from benchmarks.solvers.base_solver import BasePathSolver
from src.route_engine.engines.circular_beam import CircularBeamEngine
from src.route_engine.engines.oneway_beam import OnewayBeamEngine
from src.schema.route_schema import CircularRouteInput, OnewayRouteInput

_DEFAULT_TARGET_KM = 3.0


class CircularBeamSolver(BasePathSolver):
    def __init__(self, name: str = "Beam"):
        super().__init__(name)

    def solve(self, graph, start_node, target_node, params: dict) -> dict:
        target_km = params.get("target_km") or _DEFAULT_TARGET_KM
        inp = CircularRouteInput(start_lat=0.0, start_lon=0.0, target_km=target_km)

        engine = CircularBeamEngine(
            inp=inp,
            G=graph,
            custom_weights=params.get("custom_weights"),
            profile=params.get("profile"),
        )
        path, cost = run_circular_engine(engine, start_node, target_km)

        return {"paths": [path], "cost": cost, "overlap_ratio": 0.0}

class OnewayBeamSolver(BasePathSolver):
    def __init__(self, name: str = "Beam(oneway)"):
        super().__init__(name)

    def solve(self, graph, start_node, target_node, params: dict) -> dict:
        target_km = params.get("target_km") or _DEFAULT_TARGET_KM
        inp = OnewayRouteInput(
            start_lat=0.0, start_lon=0.0, end_lat=0.0, end_lon=0.0, target_km=target_km,
        )

        engine = OnewayBeamEngine(
            inp=inp,
            G=graph,
            custom_weights=params.get("custom_weights"),
            profile=params.get("profile"),
        )
        path, cost = run_oneway_engine(engine, start_node, target_node, target_km)
        overlap_ratio = base_shortest_path_overlap_ratio(engine, path, start_node, target_node)

        return {"paths": [path], "cost": cost, "overlap_ratio": overlap_ratio}