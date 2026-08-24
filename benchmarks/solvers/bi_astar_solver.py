from benchmarks.solvers._oneway_engine_common import base_shortest_path_overlap_ratio
from benchmarks.solvers.base_solver import BasePathSolver
from src.route_engine.engines.oneway_bi_astar import OnewayBidirectionalAstarEngine
from src.route_engine.scoring.scoring_engine import compute_distance_only_lookup
from src.schema.route_schema import OnewayRouteInput
import time

_DEFAULT_TARGET_KM = 3.0


class OnewayBidirectionalAstarSolver(BasePathSolver):
    def __init__(self, name: str = "Bidirectional A*(oneway)"):
        super().__init__(name)

    def solve(self, graph, start_node, target_node, params: dict) -> dict:
        target_km = params.get("target_km") or _DEFAULT_TARGET_KM
        inp = OnewayRouteInput(
            start_lat=0.0, start_lon=0.0, end_lat=0.0, end_lon=0.0, target_km=target_km,
        )

        engine = OnewayBidirectionalAstarEngine(
            inp=inp,
            G=graph,
            custom_weights=params.get("custom_weights"),
            profile=params.get("profile"),
        )
        scored = compute_distance_only_lookup(engine.G, engine.blocked_tags)
        engine._weight_fn    = scored["weight"]
        engine._score_lookup = scored["lookup"]

        t0 = time.perf_counter()
        nodes = engine.find_path(start_node, target_node)
        find_path_sec = time.perf_counter() - t0

        if not nodes or len(nodes) < 2:
            raise ValueError("경로 생성 실패: 유효한 편도 경로를 찾지 못했습니다 (NO_PATH)")

        cost = engine.path_cost(nodes)
        overlap_ratio = base_shortest_path_overlap_ratio(engine, nodes, start_node, target_node)
        return {"paths": [nodes], "cost": cost, "overlap_ratio": overlap_ratio, "find_path_sec": round(find_path_sec, 6)}
