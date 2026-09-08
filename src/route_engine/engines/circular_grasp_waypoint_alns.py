"""
src/route_engine/engines/circular_grasp_waypoint_alns.py

(버전 D) GRASP + ALNS. waypoint_engine_assembly.py::WaypointEngine을
construction="grasp", refinement="alns"로 고정한 얇은 래퍼다("ALNS 정제 로직 이중화 해소"
이슈) — 동작은 이전과 동일해야 한다(같은 seed·설정에서 node_ids/distance_m/
repeated_edge_ratio가 리팩터 전과 일치하는지 회귀 확인 필요).

원래 이 파일에 있던 것들의 현재 위치:
  - _improve_with_alns()  → waypoint_refinement.py::alns()
  - _AlnsStatsAccumulator → waypoint_refinement.py::AlnsStatsAccumulator
  - _build_alns_candidates/_make_cost_fn → waypoint_refinement.py::
    _alns_candidates_from_pool()/_alns_cost_fn()
  - _ALNS_* 상수 6개 → waypoint_refinement.py (이 파일에는 더 이상 두지 않는다 — 두 벌로
    두면 한쪽만 고쳤을 때 조용히 갈라진다)
어댑터 설계 근거(candidates/cost 콜백/BuildCycleRoute 재연결/candidate_limit)도 모두
waypoint_refinement.py의 "alns" 절 주석으로 옮겼다.

이름이 비슷한 circular_alns.py::CircularAlnsEngine(엣지 단위로 경로를 직접 만드는 완전히
다른 독립 구현)은 이 파일과 무관하다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

import networkx as nx

from src.route_engine.engines.grasp_waypoint_common import DEFAULT_CONFIG, GraspConfig
from src.route_engine.engines.waypoint_engine_assembly import WaypointEngine
from src.schema.route_schema import CircularRouteInput

_SEED = 42


class CircularGraspWaypointAlnsEngine(WaypointEngine):
    """alns_options는 ALNSConfig 필드 이름을 키로 하는 부분 override 매핑이다
    (ex) {"iterations": 60, "cooling_rate": 0.9}). None이면 waypoint_refinement.py의
    기본값(_ALNS_* 상수)을 그대로 쓴다 — 하이퍼파라미터 스윕 전용 주입구이며 서비스
    경로는 None이다."""

    def __init__(
        self,
        inp: CircularRouteInput,
        G: nx.Graph,
        mode: str = "distance",
        seed: int = _SEED,
        config: GraspConfig = DEFAULT_CONFIG,
        num_waypoints: Optional[int] = None,
        alns_options: Optional[Mapping[str, Any]] = None,
    ):
        super().__init__(
            inp, G, mode=mode, seed=seed, config=config, num_waypoints=num_waypoints,
            construction="grasp", refinement="alns", refinement_options=alns_options,
        )
