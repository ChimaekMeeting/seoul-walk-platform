"""
src/route_engine/engines/waypoint_refinement.py

정제(refinement) 4종(local/vnd/vns/alns)을 조립 모듈(waypoint_engine_assembly.py)이
구축(construction)과 독립적으로 조합할 수 있도록 공통 시그니처로 감싼다("Beam/GRASP
구축·정제 조립 분리" 이슈).

공통 시그니처:
    refine(G, cost_cache, pool_result, start_node, route, target_m, cfg, rng, stats=None) -> Route

rng는 vns/alns처럼 무작위성이 필요한 정제만 실제로 쓴다(local/vnd/none은 인자를 받되
무시한다 — 조립 루프가 모든 refinement를 같은 방식으로 호출할 수 있어야 하기 때문).
stats는 alns 전용 부가 통계 수집 훅(AlnsStatsAccumulator)이며, 다른 정제 함수는 받되
무시한다.

local()은 waypoint_local_search.py::local_search()를 그대로 감싼 것뿐이고(중복 구현
아님), vnd()/vns()는 각각 circular_grasp_waypoint_vnd.py::vnd()/
circular_grasp_waypoint_vns.py::_vns_loop 등을 이 모듈로 옮긴 것이다(로직은 그대로,
self.G/self.cost_cache/self.config 등 인스턴스 상태를 인자로 명시했을 뿐).

alns()는 예외다 — circular_grasp_waypoint_alns.py::CircularGraspWaypointAlnsEngine.
_improve_with_alns()는 tests/unit/test_grasp_waypoint_alns.py가
monkeypatch.setattr("...circular_grasp_waypoint_alns.alns_search", ...)로 그 모듈
자신의 alns_search 심볼을 패치해 검증하므로, 그 메서드를 이 공용 모듈로 옮기면 monkeypatch가
더 이상 적용되지 않아 테스트가 깨진다. 그래서 이 파일의 alns()는 같은 알고리즘을 별도로
다시 구현한 독립 버전이며, 기존 GRASP-Waypoint+ALNS 엔진은 이 함수를 쓰지 않고 예전
그대로 남아 있다 — 이 alns()는 새 Beam+ALNS 조합 전용이다.
"""

from __future__ import annotations

import logging
import random
from typing import Optional

import networkx as nx

from src.route_engine.engines.grasp_waypoint_common import (
    BuildCycleRoute,
    GraspConfig,
    Route,
    _edge_overlap_ratio,
    _sum_edge_length,
    better,
    construct_initial_route,
    evaluate_route,
    is_waypoint_pair_separated,
    waypoint_pair_replacement_neighbors,
    waypoint_replacement_neighbors,
)
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.engines.waypoint_local_search import local_search
from src.route_engine.engines.waypoint_pool import WaypointPoolResult
from src.route_engine.waypoint_alns import ALNSConfig, ALNSResult, alns_search

logger = logging.getLogger(__name__)


# ── none / local ─────────────────────────────────────────────────────────

def none(G, cost_cache, pool_result, start_node, route: Route, target_m, cfg, rng=None, stats=None) -> Route:
    """정제를 적용하지 않는다(구축 단계 결과를 그대로 채택) — construction 단독 성능을
    비교하고 싶을 때 쓴다."""
    return route


def local(G, cost_cache, pool_result: WaypointPoolResult, start_node, route: Route, target_m, cfg,
          rng=None, stats=None) -> Route:
    """waypoint_local_search.py::local_search()를 조립 모듈 공통 시그니처로 감싼다."""
    refined, _obj = local_search(G, cost_cache, pool_result, start_node, route, target_m, cfg)
    return refined


# ── vnd ──────────────────────────────────────────────────────────────────

_VND_NEIGHBORHOODS = (waypoint_replacement_neighbors, waypoint_pair_replacement_neighbors)
# 원래 circular_grasp_waypoint_vnd.py::_NEIGHBORHOODS와 동일. AlternativeSegment(3번째
# 이웃)는 여전히 비활성(grasp_waypoint_common.py::alternative_segment_neighbors 참고).


def vnd(G: nx.Graph, cost_cache, pool_result: WaypointPoolResult, start_node: int, route: Route,
        target_m: float, cfg: GraspConfig, rng=None, stats=None) -> Route:
    """VND: 이웃 목록(WaypointReplacement→WaypointPairReplacement)을 순서대로 검사하다가
    개선을 찾으면 첫 이웃부터 다시 시작한다. 원래
    CircularGraspWaypointVndEngine.vnd()의 로직을 그대로 옮긴 것 — vns()가 지역탐색
    단계로 그대로 재사용한다. rng/stats는 쓰지 않는다(결정적 함수)."""
    current = route
    current_obj = evaluate_route(current, target_m, target_m * cfg.distance_tolerance_ratio)
    idx = 0
    while idx < len(_VND_NEIGHBORHOODS):
        neighborhood_fn = _VND_NEIGHBORHOODS[idx]
        best_neighbor, best_neighbor_obj = current, current_obj
        for neighbor in neighborhood_fn(G, cost_cache, pool_result, start_node, current, target_m, cfg):
            neighbor_obj = evaluate_route(neighbor, target_m, target_m * cfg.distance_tolerance_ratio)
            if better(neighbor_obj, best_neighbor_obj):
                best_neighbor, best_neighbor_obj = neighbor, neighbor_obj
        if better(best_neighbor_obj, current_obj):
            current, current_obj = best_neighbor, best_neighbor_obj
            idx = 0  # 개선 시 첫 이웃으로 복귀 — VND 핵심 규칙
        else:
            idx += 1
    return current


# ── vns ──────────────────────────────────────────────────────────────────

_MAX_SHAKE_LEVEL = 4


def _shake_replace_one(G, cost_cache, pool_result: WaypointPoolResult, start_node: int, route: Route,
                        rng: random.Random) -> Optional[Route]:
    i = rng.randrange(len(route.waypoints))
    choices = [c for c in pool_result.pool_nodes if c not in route.waypoints]
    if not choices:
        return None
    new_waypoints = list(route.waypoints)
    new_waypoints[i] = rng.choice(choices)
    return BuildCycleRoute(G, cost_cache.astar_path, start_node, new_waypoints)


def _shake_replace_both(G, cost_cache, pool_result: WaypointPoolResult, start_node: int, cfg: GraspConfig,
                         rng: random.Random) -> Optional[Route]:
    n = cfg.num_waypoints
    if len(pool_result.pool_nodes) < n:
        return None
    new_waypoints = rng.sample(pool_result.pool_nodes, n)
    return BuildCycleRoute(G, cost_cache.astar_path, start_node, new_waypoints)


def _shake_reroute_segment(G, cost_cache, start_node: int, route: Route, rng: random.Random) -> Optional[Route]:
    node_ids = route.node_ids
    if len(node_ids) < 3:
        return None
    i = rng.randrange(len(node_ids) - 1)
    u, v = node_ids[i], node_ids[i + 1]
    if not G.has_edge(u, v):
        return None
    banned = frozenset({frozenset((u, v))})

    stops = [start_node, *route.waypoints, start_node]
    rerouted_nodes: list[int] = []
    for a, b in zip(stops, stops[1:]):
        leg = cost_cache.astar_path_avoiding_edges(a, b, banned)
        if leg is None:
            return None
        rerouted_nodes = rerouted_nodes + leg[1:] if rerouted_nodes else leg

    if len(rerouted_nodes) < 2:
        return None
    pruned = PathUtils(G).prune_dead_ends(rerouted_nodes)
    if len(pruned) < 2:
        return None
    return Route(
        node_ids=pruned,
        waypoints=list(route.waypoints),
        distance_m=_sum_edge_length(G, pruned),
        repeated_edge_ratio=_edge_overlap_ratio(G, pruned),
    )


def _shake(G, cost_cache, pool_result: WaypointPoolResult, start_node: int, route: Route, target_m: float,
           cfg: GraspConfig, shake_level: int, rng: random.Random) -> Optional[Route]:
    if shake_level == 1:
        return _shake_replace_one(G, cost_cache, pool_result, start_node, route, rng)
    if shake_level == 2:
        return _shake_replace_both(G, cost_cache, pool_result, start_node, cfg, rng)
    if shake_level == 3:
        return _shake_reroute_segment(G, cost_cache, start_node, route, rng)
    return construct_initial_route(G, cost_cache, pool_result, start_node, target_m, rng, cfg).route


def vns_loop(G: nx.Graph, cost_cache, pool_result: WaypointPoolResult, start_node: int, route: Route,
             target_m: float, cfg: GraspConfig, rng: random.Random) -> Route:
    """이미 지역최적(VND 적용 완료)인 route를 받아 Shake(레벨 1~4)로 교란·재개선을
    반복한다. 원래 CircularGraspWaypointVnsEngine._vns_loop의 로직을 그대로 옮긴 것 —
    최초 vnd() 호출은 포함하지 않는다(호출부가 먼저 vnd()를 적용한 뒤 이 함수에 넘겨야
    한다 — vns()가 그 순서를 대신 조립해준다)."""
    current = route
    current_obj = evaluate_route(current, target_m, target_m * cfg.distance_tolerance_ratio)
    shake_level = 1
    while shake_level <= _MAX_SHAKE_LEVEL:
        shaken = _shake(G, cost_cache, pool_result, start_node, current, target_m, cfg, shake_level, rng)
        if shaken is None:
            shake_level += 1
            continue
        candidate = vnd(G, cost_cache, pool_result, start_node, shaken, target_m, cfg)
        candidate_obj = evaluate_route(candidate, target_m, target_m * cfg.distance_tolerance_ratio)
        if better(candidate_obj, current_obj):
            current, current_obj = candidate, candidate_obj
            shake_level = 1  # 개선되면 가장 약한 교란부터 다시
        else:
            shake_level += 1
    return current


def vns(G: nx.Graph, cost_cache, pool_result: WaypointPoolResult, start_node: int, route: Route,
        target_m: float, cfg: GraspConfig, rng: random.Random, stats=None) -> Route:
    """vnd() → vns_loop() 순서로 조립한 공통 시그니처 정제 함수. 원래 GRASP+VNS 엔진의
    find_path() 안에서 `current = self._vnd_engine.vnd(...); current =
    self._vns_loop(...)`이던 두 호출과 rng 소비 순서가 완전히 동일하다."""
    current = vnd(G, cost_cache, pool_result, start_node, route, target_m, cfg)
    return vns_loop(G, cost_cache, pool_result, start_node, current, target_m, cfg, rng)


# ── alns (Beam+ALNS 등 신규 조합 전용 — 위 모듈 docstring 참고) ─────────────

_ALNS_ITERATIONS = 30
_ALNS_MAX_COST_CALLS = 3000
_ALNS_COOLING_RATE = 0.95
_ALNS_SEGMENT_LENGTH = 10
_ALNS_REACTION_FACTOR = 0.2
_ALNS_REMOVAL_FRACTION = 0.3


def _alns_candidates_from_pool(G: nx.Graph, pool_result: WaypointPoolResult) -> list[dict]:
    return [
        {"node_id": node, "lat": G.nodes[node]["lat"], "lon": G.nodes[node]["lon"]}
        for node in pool_result.pool_nodes
    ]


def _alns_cost_fn(pool_result: WaypointPoolResult, start_node: int):
    def cost(a: int, b: int) -> float:
        if a == start_node:
            return pool_result.dist_from_p1.get(b, float("inf"))
        if b == start_node:
            return pool_result.dist_from_p1.get(a, float("inf"))
        d = pool_result.distance(a, b)
        return d if d is not None else float("inf")

    return cost


class AlnsStatsAccumulator:
    """circular_grasp_waypoint_alns.py::_AlnsStatsAccumulator과 동일한 집계 로직 —
    조립 모듈(WaypointEngine)이 refinement="alns"일 때 매 grasp 반복 뒤
    pending_result/pending_accepted을 읽어 best 갱신 시점에만 record_winner()를
    호출한다(어떤 호출이 최종 best가 될지는 조립 루프만 알 수 있으므로)."""

    def __init__(self):
        self.calls = 0
        self.total_iterations = 0
        self.total_accepted_moves = 0
        self.total_failed_repairs = 0
        self.total_cost_calls = 0
        self.destroy_uses: dict[str, int] = {}
        self.repair_uses: dict[str, int] = {}
        self.accepted_alns_calls = 0
        self.winner_alns_result: Optional[ALNSResult] = None
        self.winner_alns_accepted: Optional[bool] = None
        self.pending_result: Optional[ALNSResult] = None
        self.pending_accepted: bool = False

    def record(self, result: Optional[ALNSResult]) -> None:
        if result is None:
            return
        self.calls += 1
        self.total_iterations += result.iterations
        self.total_accepted_moves += result.accepted_moves
        self.total_failed_repairs += result.failed_repairs
        self.total_cost_calls += result.cost_calls
        for stat in result.destroy_stats:
            self.destroy_uses[stat.name] = self.destroy_uses.get(stat.name, 0) + stat.uses
        for stat in result.repair_stats:
            self.repair_uses[stat.name] = self.repair_uses.get(stat.name, 0) + stat.uses

    def record_winner(self, result: Optional[ALNSResult], accepted: bool) -> None:
        self.winner_alns_result = result
        self.winner_alns_accepted = accepted
        if accepted:
            self.accepted_alns_calls += 1

    def snapshot(self) -> dict:
        winner = self.winner_alns_result
        return {
            "alns_calls": self.calls,
            "total_iterations": self.total_iterations,
            "total_accepted_moves": self.total_accepted_moves,
            "total_failed_repairs": self.total_failed_repairs,
            "total_cost_calls": self.total_cost_calls,
            "destroy_operator_uses": dict(self.destroy_uses),
            "repair_operator_uses": dict(self.repair_uses),
            "winning_iteration": {
                "accepted": self.winner_alns_accepted,
                "stop_reason": winner.stop_reason if winner else None,
                "iterations": winner.iterations if winner else None,
                "accepted_moves": winner.accepted_moves if winner else None,
                "failed_repairs": winner.failed_repairs if winner else None,
                "cost_calls": winner.cost_calls if winner else None,
                "destroy_stats": ([(s.name, s.uses, s.weight) for s in winner.destroy_stats] if winner else None),
                "repair_stats": ([(s.name, s.uses, s.weight) for s in winner.repair_stats] if winner else None),
            } if winner is not None else None,
        }


def alns(G: nx.Graph, cost_cache, pool_result: WaypointPoolResult, start_node: int, route: Route,
         target_m: float, cfg: GraspConfig, rng: random.Random,
         stats: Optional[AlnsStatsAccumulator] = None) -> Route:
    """route.waypoints를 초기 순서로 alns_search()를 1회 실행하고, 결과 경유지 순서를
    BuildCycleRoute(A*)로 다시 연결한다. accept 판정(최소거리 사후검증 + better() 비교)은
    circular_grasp_waypoint_alns.py::_improve_with_alns와 동일한 규칙이다 — 다만 이
    함수는 그 메서드를 대체하지 않는 독립 구현이다(모듈 docstring의 monkeypatch 근거
    참고).

    alns_candidates/cost_fn/alns_config는 이 호출 안에서 매번 새로 만든다 — pool_result가
    이번 find_path 호출 동안 바뀌지 않으므로 값 자체는 매번 같지만(결정적), 예전 엔진처럼
    GRASP 반복 밖에서 한 번만 만들어 재사용하지는 않는다(약간의 재계산 오버헤드는 있지만
    정확성에는 영향 없다).
    """
    alns_candidates = _alns_candidates_from_pool(G, pool_result)
    cost_fn = _alns_cost_fn(pool_result, start_node)
    alns_config = ALNSConfig(
        iterations=_ALNS_ITERATIONS,
        removal_fraction=_ALNS_REMOVAL_FRACTION,
        start_temperature_m=target_m * cfg.distance_tolerance_ratio,
        cooling_rate=_ALNS_COOLING_RATE,
        segment_length=_ALNS_SEGMENT_LENGTH,
        reaction_factor=_ALNS_REACTION_FACTOR,
        candidate_limit=cfg.rcl_size,
        max_cost_calls=_ALNS_MAX_COST_CALLS,
        seed=rng.randrange(2**31),
    )

    try:
        result = alns_search(
            candidates=alns_candidates,
            cost=cost_fn,
            initial_ids=tuple(route.waypoints),
            start_id=start_node,
            end_id=start_node,
            target_m=target_m,
            config=alns_config,
        )
    except ValueError as e:
        logger.warning("ALNS 실행 실패(%s) — 개선 없이 구축 단계 해를 그대로 씁니다.", e)
        if stats is not None:
            stats.pending_result, stats.pending_accepted = None, False
        return route

    if stats is not None:
        stats.record(result)

    new_waypoints = list(result.best.waypoint_ids)
    if new_waypoints == route.waypoints:
        if stats is not None:
            stats.pending_result, stats.pending_accepted = result, False
        return route

    if cfg.min_waypoint_separation_ratio:
        for a, b in zip(new_waypoints, new_waypoints[1:]):
            pair_m = cost_fn(a, b)
            if not is_waypoint_pair_separated(pair_m, target_m, cfg):
                if stats is not None:
                    stats.pending_result, stats.pending_accepted = result, False
                return route

    improved = BuildCycleRoute(G, cost_cache.astar_path, start_node, new_waypoints)
    if improved is None:
        if stats is not None:
            stats.pending_result, stats.pending_accepted = result, False
        return route

    tolerance = target_m * cfg.distance_tolerance_ratio
    accepted = better(evaluate_route(improved, target_m, tolerance), evaluate_route(route, target_m, tolerance))
    if stats is not None:
        stats.pending_result, stats.pending_accepted = result, accepted
    return improved if accepted else route


REFINEMENT_REGISTRY = {
    "none": none,
    "local": local,
    "vnd": vnd,
    "vns": vns,
    "alns": alns,
}
