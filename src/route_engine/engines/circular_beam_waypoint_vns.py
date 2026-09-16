"""
src/route_engine/engines/circular_beam_waypoint_vns.py

Beam 구축 + VNS 정제. waypoint_engine_assembly.py::WaypointEngine을
construction="beam", refinement="vns"로 고정하고 튜닝으로 확정한 Beam 폭을 기본값으로 둔
얇은 래퍼다.

Beam+Local/VND/ALNS에는 래퍼가 없다 — 확정값이 공용 DEFAULT_CONFIG와 같아(beam-wp-alns의
beam_width=8 등) 알고리즘별 기본값을 따로 둘 이유가 없기 때문이다. 공용 기본값과 달라진
조합에만 래퍼를 둔다(GRASP+ALNS는 circular_grasp_waypoint_alns.py).

beam_construction()은 cfg.rcl_size를 Beam 탐색 폭이자 정제 단계의 이웃 폭으로 함께 쓴다
(benchmarks/solvers/beam_waypoint_refinement_solver.py의 beam_width → rcl_size 관례와 동일).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Optional

import networkx as nx

from src.route_engine.engines.grasp_waypoint_common import DEFAULT_CONFIG, GraspConfig
from src.route_engine.engines.waypoint_engine_assembly import WaypointEngine
from src.schema.route_schema import CircularRouteInput

_SEED = 42

# ── Beam+VNS 튜닝 확정값 ──────────────────────────────────────────────────
# mode="distance"(거리 전용) 벤치마크에서 확정한 값이라 가중치가 들어간 목적함수에서는 재검증
# 대상이다.
#
# rcl_size(=beam_width)=4: 8과 통계적으로 동급(p=0.068/0.178)이면서 훨씬 저렴. 16은 정밀도가
#   실제로 우수하지만(p<0.000001) 비용 중앙값(155초)부터 60초 예산을 넘어 배제
#   (2026-09-13, run_refinement_tuning_sweep.py, 튜닝 집합 x {3,7}km x N=4).
#
# beam-wp-alns(8, 공용 기본값)와 값이 다른 이유 — 고른 기준이 다르다. 폭(rcl_size)은 Beam 구축
# 폭이자 정제 탐색 폭인데, VNS는 흔들기·VND 하강으로 좁은 구축을 만회해 폭 4·8의 거리편차가
# 같은 수준(평균 56m·57m)이고, 이웃 탐색이 O(rcl×rcl)이라 비용만 폭에 따라 크게 는다(중앙값
# 18초→37초→155초). 그래서 동급 품질 중 가장 싼 값을 골랐다. Beam+ALNS는 반대로 ALNS 제안이
# 최종 경로로 거의 채택되지 않아(폭 8에서 1/240) 구축 품질이 곧 결과라 품질이 가장 좋은 폭을
# 골랐다(같은 스윕 CSV로 확인).
BEAM_VNS_CONFIG = replace(DEFAULT_CONFIG, rcl_size=4)


class CircularBeamWaypointVnsEngine(WaypointEngine):
    """vns_options는 {"max_shake_level": N, "max_iterations": N} 형태의 정제 설정 주입구다
    (기본값은 waypoint_refinement.py의 _MAX_SHAKE_LEVEL·_MAX_ITERATIONS) —
    CircularGraspWaypointVnsEngine과 같은 관례."""

    def __init__(
        self,
        inp: CircularRouteInput,
        G: nx.Graph,
        mode: str = "distance",
        seed: int = _SEED,
        config: GraspConfig = BEAM_VNS_CONFIG,
        num_waypoints: Optional[int] = None,
        vns_options: Optional[Mapping[str, Any]] = None,
    ):
        super().__init__(
            inp, G, mode=mode, seed=seed, config=config, num_waypoints=num_waypoints,
            construction="beam", refinement="vns", refinement_options=vns_options,
        )
