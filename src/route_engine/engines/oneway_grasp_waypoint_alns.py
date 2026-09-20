"""
src/route_engine/engines/oneway_grasp_waypoint_alns.py

GRASP + ALNS 편도(oneway detour) 판. waypoint_engine_assembly.py::WaypointEngine을
OnewayRouteInput(end_lat/end_lon 보유)으로 생성해 편도로 자동 판별시키고,
construction="grasp", refinement="alns"로 고정한 얇은 래퍼다(2026-09-20, #498 확장 —
"편도 우회 정제·서비스 연결" 이슈).

circular_grasp_waypoint_alns.py::CircularGraspWaypointAlnsEngine과 거의 동일한 구조다 —
다른 점은 입력 스키마(OnewayRouteInput)뿐이다. 튜닝 확정값(GRASP_ALNS_CONFIG/
GRASP_ALNS_OPTIONS)도 그대로 재사용한다 — 이 값들은 거리·A* 연결 기준(mode="distance")에서
나온 것이라 편도/순환 여부와 무관하다. 편도 전용 재튜닝이 필요해지면 별도 과제로 남긴다.

Local/VND/VNS 편도판은 만들지 않았다 — route_service.py에 실제로 연결하는 것은 순환과
동일하게 ALNS 하나뿐이고(WalkMode.ONEWAY_RANDOM), 다른 3종을 벤치마크에서 비교하고
싶으면 이 래퍼 없이도 WaypointEngine(inp=OnewayRouteInput(...), construction="grasp",
refinement="vnd")처럼 바로 만들 수 있다(WaypointEngine이 입력 스키마 모양만으로 순환/편도를
판별하므로 새 래퍼 클래스가 없어도 된다).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

import networkx as nx

from src.route_engine.engines.circular_grasp_waypoint_alns import GRASP_ALNS_CONFIG, GRASP_ALNS_OPTIONS
from src.route_engine.engines.grasp_waypoint_common import GraspConfig
from src.route_engine.engines.waypoint_engine_assembly import WaypointEngine
from src.route_engine.scoring.scoring_engine import WeightedEdgeCost
from src.schema.route_schema import OnewayRouteInput

_SEED = 42


class OnewayGraspWaypointAlnsEngine(WaypointEngine):
    """config 기본값은 GRASP_ALNS_CONFIG, ALNS 설정 기본값은 GRASP_ALNS_OPTIONS다 —
    CircularGraspWaypointAlnsEngine과 동일(순환/편도가 튜닝을 공유한다는 뜻)."""

    def __init__(
        self,
        inp: OnewayRouteInput,
        G: nx.Graph,
        mode: str = "distance",
        seed: int = _SEED,
        config: GraspConfig = GRASP_ALNS_CONFIG,
        num_waypoints: Optional[int] = None,
        alns_options: Optional[Mapping[str, Any]] = None,
        cost_context: Optional[WeightedEdgeCost] = None,
        time_budget_sec: Optional[float] = None,
    ):
        super().__init__(
            inp, G, mode=mode, seed=seed, config=config, num_waypoints=num_waypoints,
            construction="grasp", refinement="alns",
            refinement_options={**GRASP_ALNS_OPTIONS, **(alns_options or {})},
            cost_context=cost_context,
            time_budget_sec=time_budget_sec,
        )
