"""
src/route_engine/engines/circular_grasp_waypoint_local.py

(버전 A) GRASP + 일반 지역개선. waypoint_engine_assembly.py::WaypointEngine을
construction="grasp", refinement="local"로 고정한 얇은 래퍼다("Beam/GRASP 구축·정제
조립 분리" 이슈) — 동작은 이전과 동일해야 한다(node_ids/distance_m/repeated_edge_ratio가
리팩터 전과 일치하는지 회귀 확인 필요). 원래 이 파일에 인스턴스 메서드로 있던
_local_search()는 waypoint_local_search.py::local_search()로 추출했다.
"""

from __future__ import annotations

from typing import Optional

import networkx as nx

from src.route_engine.engines.grasp_waypoint_common import DEFAULT_CONFIG, GraspConfig
from src.route_engine.engines.waypoint_engine_assembly import WaypointEngine
from src.schema.route_schema import CircularRouteInput

_SEED = 42


class CircularGraspWaypointLocalEngine(WaypointEngine):
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
            construction="grasp", refinement="local",
        )
