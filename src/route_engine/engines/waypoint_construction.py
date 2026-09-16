"""
src/route_engine/engines/waypoint_construction.py

구축(construction) 2종 — GRASP과 Beam — 을 조립 모듈(waypoint_engine_assembly.py)이
정제(refinement)와 독립적으로 조합할 수 있도록 공통 인터페이스로 감싼다("Beam/GRASP
구축·정제 조립 분리" 이슈).

공통 인터페이스:
    construct(G, cost_cache, pool_result, start_node, target_m, cfg, rng)
        -> Iterator[ConstructionResult]

GRASP은 rng로 매 반복 무작위 RCL 선택을 하며 cfg.grasp_iters회 반복해 그만큼의
ConstructionResult를 하나씩 만든다 — 조립 루프가 매 결과마다 정제를 적용하고 최선을
추적한다(기존 4개 GRASP 엔진의 find_path() 반복문과 완전히 동일).

Beam은 무작위성이 없고 beam_search를 1회만 실행해 beam_width(=cfg.rcl_size)개 조합을
내부적으로 탐색한다. 조립 루프처럼 "정제 후" 결과끼리 비교하면 beam_waypoint_solver.py의
기존 동작(정제 전 beam_width개 중 하나를 고른 뒤 정제는 아예 적용하지 않음)과 달라지므로,
이 함수 자신이 "정제 전" 최선 후보 하나만 evaluate_route/better로 골라 ConstructionResult
1개만 yield한다 — 조립 루프가 그 하나에 정제를 적용해 새 Beam+{Local,VND,VNS,ALNS}
조합을 만든다. 이 구현은 benchmarks/solvers/beam_waypoint_solver.py::
CircularBeamWaypointSolver.solve()의 pool→beam_search→build_cycle_route→최선 선택
로직을 그대로 옮긴 것이며, 그 solver 자체는 건드리지 않았다("beam-wp" 키의 기존 동작
보존). rng 인자는 시그니처를 맞추기 위한 자리이며 쓰지 않는다.

최소거리 하드 필터(2026-09-06, "GRASP/Beam 구축 단계 랭킹 공정성" 후속 논의): GRASP
구축 단계(_rank_next_waypoint_candidates)는 is_waypoint_pair_separated()로 직전
경유지와 실제 거리가 target_m*min_waypoint_separation_ratio 미만인 후보를 랭킹에서
원천 제외하지만, Beam 구축 단계에는 이 필터가 없어 물리적으로 붙어있는 후보도 그대로
통과했다. waypoint_beam.py::beam_search()는 건드리지 않고(이 저장소 시점에
rank_penalty 파라미터 자체가 없음) _with_min_separation_filter()로 cost() 콜백만
감싸 해결한다 — beam_search가 이미 cost()의 inf를 "도달 불가"로 보고 그 후보를
건너뛰므로, 최소거리 미만인 쌍에 inf를 돌려주면 새 훅 없이 동일한 하드 필터가 된다.
첫 경유지 선택(a==start_node)과 도착 폐합(b==start_node)에는 적용하지 않는다 —
GRASP도 이 두 경우엔 필터를 안 건다.

각도 다양성 페널티(2026-09-06, "GRASP/Beam 구축 단계 랭킹 공정성" 후속 논의):
GRASP 구축 단계(_rank_next_waypoint_candidates)는 점수에
angle_diversity_weight_m·|cos(각도차(p1→prev, p1→c))|를 더해 직전 경유지와 같은
방향/정반대 방향인 후보를 밀어내지만, Beam 구축 단계에는 이 항이 없었다. cost()에
직접 더하면 목표거리 비교(closed_m)에 쓰이는 실거리 자체가 오염되므로(페널티가
붙은 값이 그대로 order.distance_m/error_m이 되어버림), waypoint_beam.py::
beam_search()의 rank_penalty 훅(실거리와 분리된 랭킹 전용 보정항)에 연결해
해결한다 — _angle_diversity_rank_penalty()가 grasp_waypoint_common.py의
_bearing_rad/_angular_separation_rad를 그대로 가져다 쓴다. 첫 경유지 선택
(a==start_node)에는 GRASP과 동일하게 페널티를 적용하지 않는다(비교할 '직전 방향'이
없음).
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterator
from math import inf

import networkx as nx

from src.route_engine.engines.grasp_waypoint_common import (
    ConstructionResult,
    GraspConfig,
    _INFEASIBLE,
    _angular_separation_rad,
    _bearing_rad,
    better,
    construct_initial_route,
    evaluate_route,
)
from src.route_engine.engines.waypoint_pool import WaypointPoolResult
from src.route_engine.waypoint_beam import beam_search
from src.route_engine.waypoint_pool_beam_adapter import (
    waypoint_pool_cost_function,
    waypoint_pool_to_beam_candidates,
)
from src.route_engine.waypoint_route_builder import build_cycle_route as BuildCycleRoute


def grasp_construction(
    G: nx.Graph, cost_cache, pool_result: WaypointPoolResult, start_node: int, target_m: float,
    cfg: GraspConfig, rng: random.Random,
) -> Iterator[ConstructionResult]:
    """cfg.grasp_iters회 construct_initial_route()를 반복 호출한다 — 기존 4개 GRASP
    엔진의 find_path() 반복문 본문과 동일하다."""
    for _ in range(cfg.grasp_iters):
        yield construct_initial_route(G, cost_cache, pool_result, start_node, target_m, rng, cfg)


def _with_min_separation_filter(cost, start_node: int, min_separation_m: float):
    """GRASP의 is_waypoint_pair_separated()와 동일한 하드 필터를 beam_search()의
    cost()에 얹는다(위 모듈 docstring "최소거리 하드 필터" 참고). min_separation_m이
    0이면(비율 0) 그대로 통과시켜 필터를 끈다."""
    if not min_separation_m:
        return cost

    def wrapped(a: int, b: int) -> float:
        base = cost(a, b)
        if a == start_node or b == start_node or base == inf:
            return base
        return base if base >= min_separation_m else inf

    return wrapped


def _angle_diversity_rank_penalty(G: nx.Graph, start_node: int, weight_m: float):
    """GRASP의 _rank_next_waypoint_candidates()와 동일한 방향 다양성 페널티를
    beam_search()의 rank_penalty 훅으로 재사용한다(위 모듈 docstring "각도 다양성
    페널티" 참고). a==start_node(첫 경유지 선택)면 비교할 '직전 방향'이 없어 0을
    반환한다. weight_m이 0이면(페널티 비활성) None을 반환해 beam_search 호출부가
    rank_penalty 자체를 안 넘기게 한다."""
    if not weight_m:
        return None
    p1_data = G.nodes[start_node]

    def penalty(a: int, b: int) -> float:
        if a == start_node:
            return 0.0
        a_data, b_data = G.nodes[a], G.nodes[b]
        bearing_prev = _bearing_rad(p1_data["lat"], p1_data["lon"], a_data["lat"], a_data["lon"])
        bearing_c = _bearing_rad(p1_data["lat"], p1_data["lon"], b_data["lat"], b_data["lon"])
        separation = _angular_separation_rad(bearing_prev, bearing_c)
        return weight_m * abs(math.cos(separation))

    return penalty


def beam_construction(
    G: nx.Graph, cost_cache, pool_result: WaypointPoolResult, start_node: int, target_m: float,
    cfg: GraspConfig, rng: random.Random,
) -> Iterator[ConstructionResult]:
    """beam_search()를 1회 실행해 cfg.rcl_size개 조합("공정 비교"를 위해 beam_width로
    재사용 — beam_waypoint_solver.py 기존 관례) 중 정제 전 최선 후보 하나만 골라
    ConstructionResult 1개를 yield한다. rng는 쓰지 않는다(beam_search는 결정적)."""
    candidates = waypoint_pool_to_beam_candidates(G, pool_result)
    min_separation_m = target_m * cfg.min_waypoint_separation_ratio
    cost = _with_min_separation_filter(
        waypoint_pool_cost_function(pool_result, start_node), start_node, min_separation_m,
    )
    rank_penalty = _angle_diversity_rank_penalty(G, start_node, cfg.angle_diversity_weight_m)

    result = beam_search(
        candidates=candidates,
        cost=cost,
        start_id=start_node,
        end_id=start_node,
        target_m=target_m,
        waypoint_count=cfg.num_waypoints,
        beam_width=cfg.rcl_size,
        rank_penalty=rank_penalty,
    )
    had_valid_waypoint_pair = bool(result.orders)

    best_route, best_obj = None, _INFEASIBLE
    for order in result.orders:
        route = BuildCycleRoute(G, cost_cache.astar_path, start_node, order.waypoint_ids)
        if route is None:
            continue
        obj = evaluate_route(route, target_m, target_m * cfg.distance_tolerance_ratio)
        if best_route is None or better(obj, best_obj):
            best_obj, best_route = obj, route

    yield ConstructionResult(route=best_route, had_valid_waypoint_pair=had_valid_waypoint_pair)


CONSTRUCTION_REGISTRY = {
    "grasp": grasp_construction,
    "beam": beam_construction,
}
