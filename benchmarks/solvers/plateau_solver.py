"""
benchmarks/solvers/plateau_solver.py

src/route_engine/engines/oneway_plateau.py (Plateau method)를 BasePathSolver 규격으로
감싸는 어댑터. oneway 전용(circular 미지원)이라 solver도 하나만 존재한다.

overlap_ratio는 다른 solver들처럼 0.0 고정이 아니라, 베이스 최단경로와의 실제 중복
비율을 계산해서 담는다 — "plateau 회피"가 이 알고리즘의 존재 이유이기 때문에,
벤치마크 결과표에서 그 효과가 바로 드러나야 함.
"""

from benchmarks.solvers._oneway_engine_common import base_shortest_path_overlap_ratio, run_oneway_engine
from benchmarks.solvers.base_solver import BasePathSolver
from src.route_engine.engines.oneway_plateau import OnewayPlateauEngine
from src.schema.route_schema import OnewayRouteInput

_DEFAULT_TARGET_KM = 3.0


class PlateauSolver(BasePathSolver):
    def __init__(self, name: str = "Plateau"):
        super().__init__(name)

    def solve(self, graph, start_node, target_node, params: dict) -> dict:
        target_km = params.get("target_km") or _DEFAULT_TARGET_KM
        inp = OnewayRouteInput(
            start_lat=0.0, start_lon=0.0, end_lat=0.0, end_lon=0.0, target_km=target_km,
        )

        engine = OnewayPlateauEngine(
            inp=inp,
            G=graph,
            custom_weights=params.get("custom_weights"),
            profile=params.get("profile"),
        )
        path, cost = run_oneway_engine(engine, start_node, target_node, target_km)
        overlap_ratio = base_shortest_path_overlap_ratio(engine, path, start_node, target_node)

        return {"paths": [path], "cost": cost, "overlap_ratio": overlap_ratio}
