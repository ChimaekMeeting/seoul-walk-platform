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
from dataclasses import replace
from types import MappingProxyType
from typing import Any, Optional

import networkx as nx

from src.route_engine.engines.grasp_waypoint_common import DEFAULT_CONFIG, GraspConfig
from src.route_engine.engines.waypoint_engine_assembly import WaypointEngine
from src.schema.route_schema import CircularRouteInput

_SEED = 42

# ── GRASP+ALNS 튜닝 확정값 ────────────────────────────────────────────────
# 공용 DEFAULT_CONFIG·waypoint_refinement.py의 _ALNS_* 상수는 다른 조합(GRASP+Local/VND,
# Beam+ALNS)도 함께 쓰므로 고치지 않고, 이 조합에서만 달라진 값을 여기에 둔다.
# 모든 확정값은 mode="distance"(거리 전용) 벤치마크에서 나왔다 — 가중치가 들어간 목적함수에서는
# 재검증 대상이다. 튜닝 과정에서 "기본값 유지"로 확정된 노브 목록은
# benchmarks/run_density_stratified_scenarios.py 상단 주석에 있다.
#
# rcl_size=16: 4(p=0.0001)·8(p=0.0034) 모두보다 게이트통과율에서 유의미하게 우수
#   (2026-09-14, run_grasp_rcl_size_tuning.py, 7km, n=40/값). GRASP 4종 중 기본값을 실제로
#   바꿔야 했던 유일한 경우다(grasp-wp-local·vnd는 8이 최선).
# angle_diversity_weight_m=0.0(완전히 끄기): 기존 기본값 1500.0·대안 3000.0 모두보다 유의미하게
#   우수(2026-09-14, run_grasp_alns_param_tuning.py, p<=0.000017, 게이트통과율 1.000 대
#   0.625/0.400). 1500.0은 N=2 시절(2026-08-30) 실험에서 정해진 값이라 N=4·rcl_size=16·
#   iterations=10이 함께 적용된 조건과 안 맞았던 것으로 보인다.
GRASP_ALNS_CONFIG = replace(DEFAULT_CONFIG, rcl_size=16, angle_diversity_weight_m=0.0)

# ALNSConfig 필드 이름 기준(waypoint_refinement.py::_alns_config가 기본 ALNSConfig 위에 덮어씀).
# iterations=10: 10/20/30이 통과율·거리편차·최악값까지 통계적으로 동일(p>=0.73)한데 10이 절반
#   이하 비용(2026-09-13, run_refinement_tuning_sweep.py, 튜닝 집합 x {3,7}km x N=4). 9km(단일
#   지점·rural 교차검증 포함)까지 재확인해도 차이 없음(2026-09-14).
# candidate_limit=2(잠정값, 2026-09-15 #434): 따로 주지 않으면 복구 후보 한도가 cfg.rcl_size를
#   따라가 위 rcl_size=16이 한도까지 16으로 올린다. 전 격자 스윕(run_grasp_alns_outcome_sweep.py,
#   8출발지 x 5거리 x N{2,3,4} x 시드 10 x {2,16})에서 2는 16보다 약 3.6배 빠르고 게이트 통과율
#   차이는 유의하지 않았다(9건 대 17건, p=0.169). 거리편차(3m)·재통행률(0.001) 차이는 16이
#   근소하게 유리하다. 2는 N=4에서 remove_count=ceil(4*0.3)=2라 허용되는 하한이다 — 더 작으면
#   alns_search가 ValueError를 내고 엔진은 경고만 남긴 채 ALNS를 건너뛴다.
GRASP_ALNS_OPTIONS: Mapping[str, Any] = MappingProxyType({"iterations": 10, "candidate_limit": 2})


class CircularGraspWaypointAlnsEngine(WaypointEngine):
    """config 기본값은 GRASP_ALNS_CONFIG, ALNS 설정 기본값은 GRASP_ALNS_OPTIONS다.

    alns_options는 ALNSConfig 필드 이름을 키로 하는 부분 override 매핑이다
    (ex) {"iterations": 60, "cooling_rate": 0.9}). GRASP_ALNS_OPTIONS 위에 덮어쓰므로 일부
    노브만 스윕해도 나머지 확정값은 유지된다. 확정값 이전의 엔진 기본값(iterations=30,
    candidate_limit=rcl_size)으로 돌리려면 그 값을 명시해야 한다."""

    def __init__(
        self,
        inp: CircularRouteInput,
        G: nx.Graph,
        mode: str = "distance",
        seed: int = _SEED,
        config: GraspConfig = GRASP_ALNS_CONFIG,
        num_waypoints: Optional[int] = None,
        alns_options: Optional[Mapping[str, Any]] = None,
    ):
        super().__init__(
            inp, G, mode=mode, seed=seed, config=config, num_waypoints=num_waypoints,
            construction="grasp", refinement="alns",
            refinement_options={**GRASP_ALNS_OPTIONS, **(alns_options or {})},
        )
