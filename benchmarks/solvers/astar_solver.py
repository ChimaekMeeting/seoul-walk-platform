"""
benchmarks/solvers/astar_solver.py

src/route_engine/engines/oneway_astar.py (A*)를 BasePathSolver 규격으로 감싸는 어댑터.
Dijkstra 대비 속도/정확도 검증용 — 아직 route_service에 연결 전이라
engines/__init__.py에는 export하지 않고 여기서만 직접 import한다.
"""

from benchmarks.solvers.base_solver import BasePathSolver
from src.route_engine.engines.oneway_astar import OnewayAstarEngine
from src.route_engine.scoring.scoring_engine import calculate_custom_score
from src.schema.route_schema import OnewayRouteInput

_DEFAULT_TARGET_KM = 3.0


class OnewayAstarSolver(BasePathSolver):
    def __init__(self, name: str = "A*(oneway)"):
        super().__init__(name)

    def solve(self, graph, start_node, target_node, params: dict) -> dict:
        target_km = params.get("target_km") or _DEFAULT_TARGET_KM
        inp = OnewayRouteInput(
            start_lat=0.0, start_lon=0.0, end_lat=0.0, end_lon=0.0, target_km=target_km,
        )

        engine = OnewayAstarEngine(
            inp=inp,
            G=graph,
            custom_weights=params.get("custom_weights"),
            profile=params.get("profile"),
        )
        calculate_custom_score(engine.G, {
            "mode": engine.scoring_mode,
            "weights": engine.weights,
            "blocked_tags": engine.blocked_tags,
        })
        engine._min_ratio = engine._min_cost_per_m()

        nodes = engine.find_path(start_node, target_node)
        if not nodes or len(nodes) < 2:
            raise ValueError("경로 생성 실패: 유효한 편도 경로를 찾지 못했습니다 (NO_PATH)")

        _, cost = engine.utils.metrics(nodes)
        return {"paths": [nodes], "cost": cost, "overlap_ratio": 0.0}
