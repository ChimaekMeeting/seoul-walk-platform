"""
src/route_engine/engines/circular_grasp_waypoint_vns.py

(버전 C) GRASP + VNS(Variable Neighborhood Search). waypoint_engine_assembly.py::
WaypointEngine을 construction="grasp", refinement="vns"로 고정한 얇은 래퍼다("Beam/
GRASP 구축·정제 조립 분리" 이슈).

_vnd_engine/_vns_loop는 하위 호환을 위해 남겨뒀다 — tests/unit/test_grasp_waypoint.py의
test_vns_does_not_accept_worse_route_after_shake가 find_path()를 거치지 않고
`engine._vnd_engine.vnd(...)` → `engine._vns_loop(...)` 순서로 직접 호출한다. 이제는
별도 CircularGraspWaypointVndEngine 인스턴스를 새로 만들지 않는다(self 자신이 이미
.vnd()를 가지므로) — 예전 구현이 이 목적만으로 인스턴스를 하나 더 만들던 부분을
없앴다(G.copy()는 원래도 안 했으므로 정확성에는 영향 없다).
"""

from __future__ import annotations

import random
from typing import Optional

import networkx as nx

from src.route_engine.engines.grasp_waypoint_common import DEFAULT_CONFIG, GraspConfig, Route
from src.route_engine.engines.waypoint_engine_assembly import WaypointEngine
from src.route_engine.engines.waypoint_pool import WaypointPoolResult
from src.route_engine.engines.waypoint_refinement import vnd as _vnd, vns_loop as _vns_loop_fn
from src.schema.route_schema import CircularRouteInput

_SEED = 42


class CircularGraspWaypointVnsEngine(WaypointEngine):
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
            construction="grasp", refinement="vns",
        )
        self._vnd_engine = self  # 하위 호환: engine._vnd_engine.vnd(...) 호출부용

    def vnd(self, route: Route, pool_result: WaypointPoolResult, start_node: int, target_m: float) -> Route:
        return _vnd(self.G, self.cost_cache, pool_result, start_node, route, target_m, self.config)

    def _vns_loop(
        self, current: Route, pool_result: WaypointPoolResult, start_node: int, target_m: float,
        rng: random.Random,
    ) -> Route:
        return _vns_loop_fn(self.G, self.cost_cache, pool_result, start_node, current, target_m, self.config, rng)
