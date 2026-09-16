"""
src/route_engine/engines/circular_grasp_waypoint_vnd.py

(버전 B) GRASP + VND(Variable Neighborhood Descent). waypoint_engine_assembly.py::
WaypointEngine을 construction="grasp", refinement="vnd"로 고정한 얇은 래퍼다("Beam/
GRASP 구축·정제 조립 분리" 이슈).

.vnd(route, pool_result, start_node, target_m) 인스턴스 메서드는 하위 호환을 위해
남겨뒀다 — tests/unit/test_grasp_waypoint.py가 find_path()를 거치지 않고 이 메서드를
직접 호출하며(VNS 지역탐색 단계 검증용), circular_grasp_waypoint_vns.py도 같은
시그니처로 이 메서드를 재사용한다.
"""

from __future__ import annotations

from typing import Optional

import networkx as nx

from src.route_engine.engines.grasp_waypoint_common import DEFAULT_CONFIG, GraspConfig, Route
from src.route_engine.engines.waypoint_engine_assembly import WaypointEngine
from src.route_engine.engines.waypoint_pool import WaypointPoolResult
from src.route_engine.engines.waypoint_refinement import vnd as _vnd
from src.schema.route_schema import CircularRouteInput

_SEED = 42


class CircularGraspWaypointVndEngine(WaypointEngine):
    def __init__(
        self,
        inp: CircularRouteInput,
        G: nx.Graph,
        mode: str = "distance",
        seed: int = _SEED,
        config: GraspConfig = DEFAULT_CONFIG,
        num_waypoints: Optional[int] = None,
    ):
        super().__init__(
            inp, G, mode=mode, seed=seed, config=config, num_waypoints=num_waypoints,
            construction="grasp", refinement="vnd",
        )

    def vnd(self, route: Route, pool_result: WaypointPoolResult, start_node: int, target_m: float) -> Route:
        """waypoint_refinement.py::vnd()로 위임한다(하위 호환 시그니처 유지 — 위
        모듈 docstring 참고)."""
        return _vnd(self.G, self.cost_cache, pool_result, start_node, route, target_m, self.config)
