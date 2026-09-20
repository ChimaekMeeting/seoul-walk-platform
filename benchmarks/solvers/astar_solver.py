from benchmarks.solvers._oneway_engine_common import baseline_shortest_metrics
from benchmarks.solvers.base_solver import BasePathSolver
from src.route_engine.engines.oneway_astar import OnewayAstarEngine
from src.schema.route_schema import OnewayRouteInput
import time

_DEFAULT_TARGET_KM = 3.0


class OnewayAstarSolver(BasePathSolver):
    def __init__(self, name: str = "A*(oneway)"):
        super().__init__(name)

    def solve(self, graph, start_node, target_node, params: dict) -> dict:
        target_km = params.get("target_km") or _DEFAULT_TARGET_KM
        inp = OnewayRouteInput(
            start_lat=0.0, start_lon=0.0, end_lat=0.0, end_lon=0.0, target_km=target_km,
        )

        t0 = time.perf_counter()
        engine = OnewayAstarEngine(
            inp=inp,
            G=graph,
            custom_weights=params.get("custom_weights"),
            cost_context=params.get("cost_context"),
        )
        t1 = time.perf_counter()

        candidates = engine.find_path(start_node, target_node)
        t2 = time.perf_counter()
        print(f"[A* 진단] G.assign={t1-t0:.3f}s, find_path={t2-t1:.3f}s")

        if not candidates or len(candidates[0]) < 2:
            raise ValueError("경로 생성 실패: 유효한 편도 경로를 찾지 못했습니다 (NO_PATH)")

        nodes = candidates[0]
        cost = engine.path_cost(nodes)
        baseline = baseline_shortest_metrics(engine, nodes, start_node, target_node)
        baseline_km, baseline_overlap = baseline if baseline is not None else (None, None)
        return {"paths": [nodes], "cost": cost,
                "baseline_shortest_km": baseline_km,
                "baseline_shortest_overlap_ratio": baseline_overlap,
                "find_path_sec": round(t2 - t1, 6)}
