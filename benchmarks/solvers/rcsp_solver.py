"""
benchmarks/solvers/rcsp_solver.py

src/route_engine/engines/circular_rcsp.py, oneway_rcsp.py (RCSP - 자원제약 최단경로)를
BasePathSolver 규격으로 감싸는 어댑터. circular/oneway 둘 다 벤치마크 대상이라
두 버전을 각각 제공한다 — oneway_rcsp가 Plateau(oneway 전용)와 직접 비교되는 대상.
"""

from benchmarks.solvers._circular_engine_common import run_circular_engine
from benchmarks.solvers._oneway_engine_common import run_oneway_engine
from benchmarks.solvers.base_solver import BasePathSolver
from src.route_engine.engines.circular_rcsp import CircularRcspEngine
from src.route_engine.engines.oneway_rcsp import OnewayRcspEngine
from src.schema.route_schema import CircularRouteInput, OnewayRouteInput
from benchmarks.solvers._oneway_engine_common import base_shortest_path_overlap_ratio

_DEFAULT_TARGET_KM = 3.0


class CircularRcspSolver(BasePathSolver):
    def __init__(self, name: str = "RCSP(circular)"):
        super().__init__(name)

    def solve(self, graph, start_node, target_node, params: dict) -> dict:
        target_km = params.get("target_km") or _DEFAULT_TARGET_KM
        inp = CircularRouteInput(start_lat=0.0, start_lon=0.0, target_km=target_km)

        engine = CircularRcspEngine(
            inp=inp,
            G=graph,
            custom_weights=params.get("custom_weights"),
            profile=params.get("profile"),
        )
        path, cost = run_circular_engine(engine, start_node, target_km)

        return {"paths": [path], "cost": cost, "overlap_ratio": 0.0}


class OnewayRcspSolver(BasePathSolver):
    def __init__(self, name: str = "RCSP(oneway)"):
        super().__init__(name)

    def solve(self, graph, start_node, target_node, params: dict) -> dict:
        target_km = params.get("target_km") or _DEFAULT_TARGET_KM
        inp = OnewayRouteInput(
            start_lat=0.0, start_lon=0.0, end_lat=0.0, end_lon=0.0, target_km=target_km,
        )

        engine = OnewayRcspEngine(
            inp=inp,
            G=graph,
            custom_weights=params.get("custom_weights"),
            profile=params.get("profile"),
        )
        path, cost = run_oneway_engine(engine, start_node, target_node, target_km)
        overlap_ratio = base_shortest_path_overlap_ratio(engine, path, start_node, target_node)
        return {"paths": [path], "cost": cost, "overlap_ratio": overlap_ratio}