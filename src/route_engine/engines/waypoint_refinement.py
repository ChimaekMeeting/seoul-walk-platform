"""
src/route_engine/engines/waypoint_refinement.py

정제(refinement) 4종(local/vnd/vns/alns)을 조립 모듈(waypoint_engine_assembly.py)이
구축(construction)과 독립적으로 조합할 수 있도록 공통 시그니처로 감싼다("Beam/GRASP
구축·정제 조립 분리" 이슈).

공통 시그니처:
    refine(G, cost_cache, pool_result, start_node, route, target_m, cfg, rng,
           stats=None, options=None) -> Route

rng는 vns/alns처럼 무작위성이 필요한 정제만 실제로 쓴다(local/vnd/none은 인자를 받되
무시한다 — 조립 루프가 모든 refinement를 같은 방식으로 호출할 수 있어야 하기 때문).
stats는 alns 전용 통계·1회분 상태 훅(AlnsStatsAccumulator)이며, 다른 정제 함수는 받되
무시한다.

options는 정제별 하이퍼파라미터 주입구다("ALNS 정제 로직 이중화 해소" 이슈). alns()에서는
ALNSConfig 필드 이름을 키로 하는 부분 override 매핑이고(ex) {"iterations": 60,
"cooling_rate": 0.9}), 나머지 정제는 받되 무시한다. GraspConfig를 넓히지 않은 이유는
VND의 이웃 목록(_VND_NEIGHBORHOODS)·VNS의 교란 레벨(_MAX_SHAKE_LEVEL)이 모듈 상수인 현재
관례와 어긋나고, 모든 조합이 쓰지도 않는 노브를 들고 다니게 되기 때문이다(ex) beam x local
실행이 alns_cooling_rate를 보유). 어떤 정제가 options를 실제로 해석하는지는 이 파일의
OPTIONS_AWARE_REFINEMENTS가 단일 기준이며, 조립 계층이 그 밖의 정제에 주입이 들어오면
거부한다.

local()은 waypoint_local_search.py::local_search()를 그대로 감싼 것뿐이고(중복 구현
아님), vnd()/vns()는 각각 circular_grasp_waypoint_vnd.py::vnd()/
circular_grasp_waypoint_vns.py::_vns_loop 등을 이 모듈로 옮긴 것이다(로직은 그대로,
self.G/self.cost_cache/self.config 등 인스턴스 상태를 인자로 명시했을 뿐).

alns()도 같은 규칙을 따른다. 예전에는 circular_grasp_waypoint_alns.py::
_improve_with_alns()와 별도로 다시 구현한 두 벌이었고(테스트가 그 모듈 자신의 alns_search
심볼을 monkeypatch했기 때문), 그 결과 _ALNS_* 상수 6개와 최소거리 사후검증이 두 파일에
복제돼 있었다 — 한쪽만 고치면 조용히 갈라지는 상태였다. 이제 이 파일이 유일한 구현이고
circular_grasp_waypoint_alns.py는 다른 3종과 동일한 얇은 래퍼이며, 테스트는
"...waypoint_refinement.alns_search"를 patch한다.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Optional

import networkx as nx

from src.route_engine.engines.grasp_waypoint_common import (
    BuildCycleRoute,
    GraspConfig,
    Route,
    RouteObjective,
    _edge_overlap_ratio,
    _sum_edge_length,
    _sum_weighted_cost,
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

def none(G, cost_cache, pool_result, start_node, route: Route, target_m, cfg, rng=None,
         stats=None, options=None) -> Route:
    """정제를 적용하지 않는다(구축 단계 결과를 그대로 채택) — construction 단독 성능을
    비교하고 싶을 때 쓴다."""
    return route


def local(G, cost_cache, pool_result: WaypointPoolResult, start_node, route: Route, target_m, cfg,
          rng=None, stats=None, options=None) -> Route:
    """waypoint_local_search.py::local_search()를 조립 모듈 공통 시그니처로 감싼다."""
    refined, _obj = local_search(G, cost_cache, pool_result, start_node, route, target_m, cfg)
    return refined


# ── vnd ──────────────────────────────────────────────────────────────────

_VND_NEIGHBORHOODS = (waypoint_replacement_neighbors, waypoint_pair_replacement_neighbors)
# 원래 circular_grasp_waypoint_vnd.py::_NEIGHBORHOODS와 동일. AlternativeSegment(3번째
# 이웃)는 여전히 비활성(grasp_waypoint_common.py::alternative_segment_neighbors 참고).


def vnd(G: nx.Graph, cost_cache, pool_result: WaypointPoolResult, start_node: int, route: Route,
        target_m: float, cfg: GraspConfig, rng=None, stats=None, options=None) -> Route:
    """VND: 이웃 목록(WaypointReplacement→WaypointPairReplacement)을 순서대로 검사하다가
    개선을 찾으면 첫 이웃부터 다시 시작한다. 원래
    CircularGraspWaypointVndEngine.vnd()의 로직을 그대로 옮긴 것 — vns()가 지역탐색
    단계로 그대로 재사용한다. rng/stats/options는 쓰지 않는다(결정적 함수)."""
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

# vns_loop 1회 호출의 총 반복(교란 시도) 상한("GRASP VNS 반복 종료 조건" 이슈, 2026-09-16).
# 개선되면 shake_level이 1로 돌아가므로 max_shake_level만으로는 반복 횟수에 상한이 없다.
# 개선이 k번 일어난 호출의 반복 수는 최대 (k+1)*max_shake_level이므로, 12는 기본 레벨
# 상한(4)에서 개선 후 복귀 2번까지는 끝까지 탐색하게 두는 값이다.
# 계측(mode="distance", 홍대, seed=42, 이 PC 단독 실행): 3km N=2·3 구축 40회는 호출당
# 4~9회로 이 상한에 걸리지 않았고, 9km N=3 구축 1회는 15회(개선 4번, 76초)였다. 품질 영향은
# 아직 비교하지 않았다 — "VNS 조합 재검토 스크리닝" 이슈에서 다시 본다.
_MAX_ITERATIONS = 12


def _shake_replace_one(G, cost_cache, pool_result: WaypointPoolResult, start_node: int, route: Route,
                        rng: random.Random) -> Optional[Route]:
    i = rng.randrange(len(route.waypoints))
    choices = [c for c in pool_result.pool_nodes if c not in route.waypoints]
    if not choices:
        return None
    new_waypoints = list(route.waypoints)
    new_waypoints[i] = rng.choice(choices)
    return BuildCycleRoute(
        G, cost_cache.astar_path, start_node, new_waypoints, cost_context=cost_cache.cost_context,
    )


def _shake_replace_both(G, cost_cache, pool_result: WaypointPoolResult, start_node: int, cfg: GraspConfig,
                         rng: random.Random) -> Optional[Route]:
    n = cfg.num_waypoints
    if len(pool_result.pool_nodes) < n:
        return None
    new_waypoints = rng.sample(pool_result.pool_nodes, n)
    return BuildCycleRoute(
        G, cost_cache.astar_path, start_node, new_waypoints, cost_context=cost_cache.cost_context,
    )


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
        weighted_cost_m=_sum_weighted_cost(G, pruned, cost_cache.cost_context),
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
             target_m: float, cfg: GraspConfig, rng: random.Random,
             max_shake_level: int = _MAX_SHAKE_LEVEL,
             max_iterations: Optional[int] = _MAX_ITERATIONS) -> Route:
    """이미 지역최적(VND 적용 완료)인 route를 받아 Shake(레벨 1~max_shake_level)로 교란·
    재개선을 반복한다. 원래 CircularGraspWaypointVnsEngine._vns_loop의 로직을 그대로 옮긴
    것 — 최초 vnd() 호출은 포함하지 않는다(호출부가 먼저 vnd()를 적용한 뒤 이 함수에 넘겨야
    한다 — vns()가 그 순서를 대신 조립해준다).

    종료 조건은 둘 중 먼저 오는 쪽이다.
      - shake_level이 max_shake_level을 넘음(개선 없이 모든 레벨을 소진) — 원래 규칙.
      - 반복 수가 max_iterations에 도달. 반복 1회는 교란 시도 1회이며 교란이 None인 시도도
        센다. None이면 상한 없이 원래 규칙만 쓴다(상한 도입 전 결과 재현용).

    다른 후보였던 조건을 고르지 않은 이유:
      - 개선 없는 연속 반복 상한: 이 루프에서는 실패할 때마다 레벨이 오르므로 연속 실패는
        이미 max_shake_level번을 넘을 수 없다. 개선이 이어지는 경우를 막지 못해 효과가 없다.
      - 경과 시간 상한: 같은 seed라도 기계 부하(벤치마크 워커 경합)에 따라 결과가 달라져
        짝지은 비교와 재현성이 깨진다.

    두 인자는 하위 호환을 위해 기본값을 갖는 키워드 인자다 — 이 값을 넘기지 않는 호출부
    (circular_grasp_waypoint_vns.py::_vns_loop 등)는 기본 상한을 쓴다."""
    current = route
    current_obj = evaluate_route(current, target_m, target_m * cfg.distance_tolerance_ratio)
    shake_level = 1
    iterations = 0
    while shake_level <= max_shake_level:
        if max_iterations is not None and iterations >= max_iterations:
            logger.debug("VNS 반복 상한(%d회)에 도달해 종료합니다: shake_level=%d", max_iterations, shake_level)
            break
        iterations += 1
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


_VNS_OPTION_KEYS = frozenset({"max_shake_level", "max_iterations"})


def _is_positive_int(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 1


def _vns_loop_limits(options: Optional[Mapping[str, Any]]) -> tuple[int, Optional[int]]:
    """options에서 (교란 레벨 상한, 총 반복 상한)을 읽는다. 모르는 키는 즉시 실패시킨다 —
    alns 쪽에서 dataclasses.replace()가 해주던 역할을 여기서는 직접 한다(VNS에는 대응하는
    설정 dataclass가 없다). bool을 int로 통과시키지 않는 것은 waypoint_alns.py의 설정 검증
    관례와 같다. max_iterations만 None(상한 없음)을 허용한다."""
    if not options:
        return _MAX_SHAKE_LEVEL, _MAX_ITERATIONS
    unknown = set(options) - _VNS_OPTION_KEYS
    if unknown:
        raise TypeError(
            f"vns가 모르는 options 키: {sorted(unknown)} — 사용 가능: {sorted(_VNS_OPTION_KEYS)}"
        )
    level = options.get("max_shake_level", _MAX_SHAKE_LEVEL)
    if not _is_positive_int(level):
        raise ValueError(f"max_shake_level은 1 이상의 정수여야 합니다: {level!r}")
    iterations = options.get("max_iterations", _MAX_ITERATIONS)
    if iterations is not None and not _is_positive_int(iterations):
        raise ValueError(f"max_iterations는 1 이상의 정수 또는 None이어야 합니다: {iterations!r}")
    return level, iterations


def vns(G: nx.Graph, cost_cache, pool_result: WaypointPoolResult, start_node: int, route: Route,
        target_m: float, cfg: GraspConfig, rng: random.Random, stats=None,
        options: Optional[Mapping[str, Any]] = None) -> Route:
    """vnd() → vns_loop() 순서로 조립한 공통 시그니처 정제 함수. 원래 GRASP+VNS 엔진의
    find_path() 안에서 `current = self._vnd_engine.vnd(...); current =
    self._vns_loop(...)`이던 두 호출과 rng 소비 순서가 완전히 동일하다.

    options는 {"max_shake_level": N}(기본 _MAX_SHAKE_LEVEL=4)과 {"max_iterations": N 또는
    None}(기본 _MAX_ITERATIONS=12, 의미는 vns_loop 참고)을 받는다. 내부 vnd() 호출에는
    아무것도 전달하지 않는다 — vnd는 아직 options를 해석하지 않으므로 이름 공간을 나눌
    필요가 없다(OPTIONS_AWARE_REFINEMENTS 참고).

    레벨 의미에 주의한다: _shake()가 분기하는 것은 1(경유지 1개 교체)·2(전체 재추출)·
    3(구간 우회)뿐이고 4 이상은 전부 else로 떨어져 construct_initial_route 전체 재구축이
    된다. 따라서 4를 넘는 값은 "새로운 교란 단계"가 아니라 "전체 재구축을 몇 번 더
    시도하는가"로 동작한다(매번 rng가 다르므로 다중 재시작 효과는 있다)."""
    max_shake_level, max_iterations = _vns_loop_limits(options)
    current = vnd(G, cost_cache, pool_result, start_node, route, target_m, cfg)
    return vns_loop(
        G, cost_cache, pool_result, start_node, current, target_m, cfg, rng,
        max_shake_level=max_shake_level, max_iterations=max_iterations,
    )


# ── alns ─────────────────────────────────────────────────────────────────
#
# waypoint_alns.py::alns_search는 그래프·A*를 전혀 모르는 순수 함수다(외부 후보 풀 +
# cost 콜백 + 초기 순서만 받음 — 2026-08-30 docs/route_engine/README.md "경유지 ALNS
# 독립 함수" 절 참고). 아래 어댑터가 NetworkX 그래프·WaypointPoolResult와 그 함수 사이를
# 잇는다:
#   - candidates: pool_result.pool_nodes를 {node_id, lat, lon} dict로 변환.
#   - cost(a, b): pool_result.distance()를 감싸되, p1(start_node)은 pool에 없으므로
#     (waypoint_pool.py 설계상 자기 자신이라 제외됨) dist_from_p1으로 따로 처리하고,
#     도달 불가(None)는 ALNS 계약대로 inf로 변환한다.
#   - ALNS가 고른 최종 경유지 순서는 추상적인 거리 합만 보장하므로, 실제 노드열은 항상
#     BuildCycleRoute(A*)로 다시 만든다(다른 정제와 동일한 "raw 추정치 금지, 실제 경로
#     합산" 원칙).
#
# candidate_limit(=cfg.rcl_size)로 repair 단계가 매 반복 평가하는 후보 수를 Local/VND/VNS와
# 비슷한 규모로 제한한다 — 후보 풀 전체(target_km에 따라 수천 개)를 매 반복 평가하면
# 실행 시간이 감당할 수 없이 늘어난다(waypoint_alns.py 자신의 docstring도 "큰 후보 풀은
# candidate_limit·max_cost_calls와 외부 거리 캐시를 사용해 계산량을 관리해야 한다"고 명시).
#
# 경유지 개수: alns_search는 initial_ids: Sequence[int]를 받고 remove_count =
# ceil(len(initial_ids) * removal_fraction)으로 계산해 처음부터 N-제네릭이다.

# ALNS 설정 기본값(하이퍼파라미터 튜닝 시작값이며 서비스 품질 보장값이 아니다).
# waypoint_alns.py 자신의 기본값(iterations=200)을 구축 반복(grasp_iters=24)과 그대로
# 곱하면 24*200회 destroy-repair가 되어 실행시간이 감당할 수 없이 늘어난다. 팀원 실행기
# (benchmarks/runner/waypoint_alns.py) 기본값(iterations=30)에 맞춰 구축 1회당 ALNS는
# 가볍게 개선만 담당하게 한다 — VND/VNS와 비슷한 자릿수의 실행시간을 노린 값이다.
# 스윕은 이 상수를 고치지 말고 options로 덮어쓴다(위 모듈 docstring 참고).
_ALNS_ITERATIONS = 30
_ALNS_MAX_COST_CALLS = 3000
_ALNS_COOLING_RATE = 0.95
_ALNS_SEGMENT_LENGTH = 10
_ALNS_REACTION_FACTOR = 0.2
_ALNS_REMOVAL_FRACTION = 0.3  # cfg.num_waypoints=2(기본값)에서는 ceil(2*0.3)=1개만 제거됨
                              # (waypoint_alns.py 규칙). num_waypoints를 늘리면 제거 개수도
                              # 비례해 늘어난다(ceil(N*removal_fraction)).


def _alns_candidates_from_pool(G: nx.Graph, pool_result: WaypointPoolResult) -> list[dict]:
    """pool_result.pool_nodes를 waypoint_alns.py가 요구하는 {node_id, lat, lon} dict
    목록으로 변환한다(WaypointCandidate 계약, src/route_engine/waypoint_types.py 참고)."""
    return [
        {"node_id": node, "lat": G.nodes[node]["lat"], "lon": G.nodes[node]["lon"]}
        for node in pool_result.pool_nodes
    ]


def _alns_cost_fn(pool_result: WaypointPoolResult, start_node: int):
    """waypoint_alns.py::CostFunction 계약(대칭 거리 m, 도달 불가는 inf)에 맞춘 cost(a,b).

    p1(start_node)은 waypoint_pool.py 설계상 pool_nodes에 포함되지 않으므로(자기 자신이라
    제외됨), pool_result.distance()에 직접 넘기면 ValueError가 난다 — p1이 관여하는 두
    구간(start→첫 경유지, 마지막 경유지→start)은 dist_from_p1으로 따로 처리한다."""

    def cost(a: int, b: int) -> float:
        if a == start_node:
            return pool_result.dist_from_p1.get(b, float("inf"))
        if b == start_node:
            return pool_result.dist_from_p1.get(a, float("inf"))
        d = pool_result.distance(a, b)
        return d if d is not None else float("inf")

    return cost


def _alns_adapter(G: nx.Graph, pool_result: WaypointPoolResult, start_node: int,
                  stats: Optional["AlnsStatsAccumulator"]):
    """(candidates, cost_fn)을 만들되, 조립 루프가 find_path 1회마다 새로 만드는 stats에
    첫 호출 결과를 캐시한다 — 그 1회 동안 pool_result/start_node는 바뀌지 않으므로 구축
    반복(기본 24회)마다 풀 크기만큼의 재구성을 되풀이할 이유가 없다(예전 GRASP+ALNS 엔진이
    find_path 안에서 한 번만 만들던 것과 같은 효과). stats가 None인 직접 호출(단위 테스트
    등)에서는 매번 새로 만든다 — 값 자체는 동일하다."""
    if stats is not None and stats.adapter_cache is not None:
        return stats.adapter_cache
    adapter = (_alns_candidates_from_pool(G, pool_result), _alns_cost_fn(pool_result, start_node))
    if stats is not None:
        stats.adapter_cache = adapter
    return adapter


def _alns_config(target_m: float, cfg: GraspConfig, rng: random.Random,
                 options: Optional[Mapping[str, Any]]) -> ALNSConfig:
    """모듈 상수 + 호출 문맥(target_m/cfg/rng)으로 기본 ALNSConfig를 만들고, options에
    들어온 필드만 덮어쓴다. options에 ALNSConfig가 갖지 않는 키가 있으면 replace()가
    TypeError를 내며 즉시 실패한다(조용한 오타 방지).

    seed는 options 유무와 상관없이 항상 rng에서 먼저 뽑는다 — options가 rng 소비 순서를
    바꾸면 같은 seed의 재현성이 깨지기 때문이다(options["seed"]가 그 값을 덮어써도 소비는
    이미 일어난 상태로 남는다).

    ALNS는 alns_search() 내부에서 매번 Random(config.seed)를 새로 만든다(외부 rng를
    공유받지 않는 순수 함수 설계 — waypoint_alns.py 참고). seed를 고정해두면 initial_ids만
    다를 뿐 구축 반복 내내 destroy-repair 난수열 자체가 완전히 동일해져 탐색 다양성이
    줄어든다(실측 확인, 2026-08-30) — 매 호출 새 seed를 뽑아 이 문제를 없앤다."""
    base = ALNSConfig(
        iterations=_ALNS_ITERATIONS,
        removal_fraction=_ALNS_REMOVAL_FRACTION,
        # tolerance(evaluate_route에 쓰는 target_m*distance_tolerance_ratio)와 같은
        # 스케일로 맞춘다(2026-09-03) — 이전에는 고정 150.0m 상수였는데, tolerance가
        # target_m 비례 비율로 바뀌면서 target_m=3000이 아닌 호출에서는 "같은 스케일"
        # 이라는 원래 의도가 깨졌다.
        start_temperature_m=target_m * cfg.distance_tolerance_ratio,
        cooling_rate=_ALNS_COOLING_RATE,
        segment_length=_ALNS_SEGMENT_LENGTH,
        reaction_factor=_ALNS_REACTION_FACTOR,
        candidate_limit=cfg.rcl_size,
        max_cost_calls=_ALNS_MAX_COST_CALLS,
        seed=rng.randrange(2**31),
    )
    if not options:
        return base
    return replace(base, **dict(options))


class AlnsStatsAccumulator:
    """구축 반복(grasp_iters회)에 걸친 ALNS 호출들의 destroy/repair operator 통계를 모은다
    (요청서 §4.4/§7 "operator별 사용 횟수·개선 횟수·수락 횟수·best 개선 횟수" 대응).

    waypoint_alns.py::ALNSResult가 실제로 제공하는 값은 operator별 uses(사용 횟수)와 호출
    종료 시점의 weight(적응형 가중치 — 그 자체가 누적 보상의 이동평균이라 "얼마나
    성공적이었는지"의 대리 지표)뿐이다. operator별 개선 횟수·SA 수락 횟수는 ALNSResult가
    분리해서 주지 않는다(accepted_moves/failed_repairs는 호출 전체 합계로만 제공됨) — 이
    클래스는 모듈이 실제로 반환하는 값만 정직하게 집계하고, 반환하지 않는 값을 추정해서
    채우지 않는다.

    조립 모듈(WaypointEngine)은 refinement="alns"일 때 find_path 1회마다 이 객체를 하나
    만들고, 매 구축 반복 뒤 pending_result/pending_accepted을 읽어 best 갱신 시점에만
    record_winner()를 호출한다(어떤 호출이 최종 best가 될지는 조립 루프만 알 수 있다).
    adapter_cache는 통계가 아니라 그 1회분 어댑터 캐시다(_alns_adapter 참고)."""

    def __init__(self):
        self.calls = 0
        self.total_iterations = 0
        self.total_accepted_moves = 0
        self.total_failed_repairs = 0
        self.total_cost_calls = 0
        self.destroy_uses: dict[str, int] = {}
        self.repair_uses: dict[str, int] = {}
        self.stop_reason_counts: dict[str, int] = {}  # 반복 전체의 종료 사유 분포
        self.remove_count_used: Optional[int] = None  # N 고정이라 실행 내내 같은 값
        self.accepted_alns_calls = 0  # best_route 갱신 시점에 ALNS 결과가 실제 채택된 횟수
        self.winner_alns_result: Optional[ALNSResult] = None
        self.winner_alns_accepted: Optional[bool] = None
        self.winner_outcome: Optional[str] = None
        self.pending_result: Optional[ALNSResult] = None
        self.pending_accepted: bool = False
        self.pending_outcome: Optional[str] = None
        # alns() 호출 1회가 끝난 결과(ALNS_OUTCOMES 중 하나)의 분포 — winning_iteration은
        # 최종 best를 만든 1회만 보여 주므로, "ALNS 제안이 왜 전부 버려졌는지"는 이 분포로 본다.
        self.outcome_counts: dict[str, int] = {}
        # better() 비교까지 간 호출에서 승패를 가른 비교 키(_decisive_key) 분포.
        self.comparison_decided_by: dict[str, dict[str, int]] = {}
        self.adapter_cache: Optional[tuple[list[dict], Any]] = None  # (candidates, cost_fn)

    def record(self, result: Optional[ALNSResult]) -> None:
        if result is None:  # alns_search 자체가 실패(ValueError)했던 호출
            return
        self.calls += 1
        self.total_iterations += result.iterations
        self.total_accepted_moves += result.accepted_moves
        self.total_failed_repairs += result.failed_repairs
        self.total_cost_calls += result.cost_calls
        self.stop_reason_counts[result.stop_reason] = (
            self.stop_reason_counts.get(result.stop_reason, 0) + 1
        )
        self.remove_count_used = result.remove_count
        for stat in result.destroy_stats:
            self.destroy_uses[stat.name] = self.destroy_uses.get(stat.name, 0) + stat.uses
        for stat in result.repair_stats:
            self.repair_uses[stat.name] = self.repair_uses.get(stat.name, 0) + stat.uses

    def record_winner(self, result: Optional[ALNSResult], accepted: bool,
                      outcome: Optional[str] = None) -> None:
        """best_route가 이 구축 반복으로 갱신될 때마다 호출 — 최종적으로 채택된 경로를
        만든(또는 시도했으나 기각된) ALNS 실행의 상세를 별도로 남긴다."""
        self.winner_alns_result = result
        self.winner_alns_accepted = accepted
        self.winner_outcome = outcome
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
            "stop_reason_counts": dict(self.stop_reason_counts),
            "remove_count_used": self.remove_count_used,
            "outcome_counts": dict(self.outcome_counts),
            "comparison_decided_by": {k: dict(v) for k, v in self.comparison_decided_by.items()},
            # best_route를 만든 마지막 갱신 시점의 ALNS 실행(최종 채택된 경로와 가장
            # 직접적으로 연결된 단일 실행 — winner_alns_accepted=False면 이 실행의 제안은
            # better()에 의해 기각되고 구축 단계 raw 해가 최종 채택됐다는 뜻).
            "winning_iteration": {
                "accepted": self.winner_alns_accepted,
                "outcome": self.winner_outcome,
                "stop_reason": winner.stop_reason if winner else None,
                "iterations": winner.iterations if winner else None,
                "accepted_moves": winner.accepted_moves if winner else None,
                "failed_repairs": winner.failed_repairs if winner else None,
                "cost_calls": winner.cost_calls if winner else None,
                "destroy_stats": ([(s.name, s.uses, s.weight) for s in winner.destroy_stats] if winner else None),
                "repair_stats": ([(s.name, s.uses, s.weight) for s in winner.repair_stats] if winner else None),
            } if winner is not None else None,
        }


# alns() 1회 호출이 끝나는 경로. accepted만 교체이고 나머지는 모두 구축 해 유지다.
ALNS_OUTCOMES = (
    "search_failed",         # alns_search가 ValueError(설정·입력 검증 실패)
    "unchanged",             # ALNS best 경유지 순서가 초기 순서와 같음
    "separation_violation",  # 경유지 최소거리 조건 위반
    "rebuild_failed",        # BuildCycleRoute(A*) 재연결 실패
    "not_better",            # 재연결 경로가 better()에서 구축 해를 못 이김
    "accepted",
)


def _decisive_key(a: RouteObjective, b: RouteObjective) -> str:
    """a와 b의 sort_key에서 처음 달라지는 항목 이름을 돌려준다(같으면 "equal").
    sort_key는 feasible 여부에 따라 두 번째·세 번째 항목의 의미가 뒤바뀌므로
    (RouteObjective.sort_key 참고) 이름도 그에 맞춰 붙인다."""
    ka, kb = a.sort_key(), b.sort_key()
    if ka[0] != kb[0]:
        return "feasibility"
    names = (
        ("repeated_edge_ratio", "preference_penalty_ratio", "distance_error_m") if ka[0] == 0
        else ("distance_error_m", "repeated_edge_ratio", "preference_penalty_ratio")
    )
    for name, x, y in zip(names, ka[1:], kb[1:]):
        if x != y:
            return name
    return "equal"


def _record_pending(stats: Optional[AlnsStatsAccumulator], result: Optional[ALNSResult],
                    accepted: bool, outcome: str, decided_by: Optional[str] = None) -> None:
    if stats is not None:
        stats.pending_result, stats.pending_accepted = result, accepted
        stats.pending_outcome = outcome
        stats.outcome_counts[outcome] = stats.outcome_counts.get(outcome, 0) + 1
        if decided_by is not None:
            bucket = stats.comparison_decided_by.setdefault(outcome, {})
            bucket[decided_by] = bucket.get(decided_by, 0) + 1


def alns(G: nx.Graph, cost_cache, pool_result: WaypointPoolResult, start_node: int, route: Route,
         target_m: float, cfg: GraspConfig, rng: random.Random,
         stats: Optional[AlnsStatsAccumulator] = None,
         options: Optional[Mapping[str, Any]] = None) -> Route:
    """route.waypoints를 초기 순서로 alns_search()를 1회 실행하고, 결과 경유지 순서를
    BuildCycleRoute(A*)로 다시 연결한다.

    alns_search의 자체 수락 기준(_rank)은 distance_error_m만 본다 — repeated_edge_ratio도,
    GraspConfig.angle_diversity_weight_m·min_waypoint_separation_ratio도 알지 못한다.
    그래서 ALNS가 목표거리에는 더 가까우면서 왕복 퇴화에 가까운(반복률 높은) 조합을
    "best"로 고를 수 있다 — 실측으로 확인됨(2026-08-30, target_km=3.0 seed=42: ALNS 결과를
    그대로 쓰면 overlap_ratio=0.40까지 나빠짐). VND/VNS가 이웃/Shake 결과를 evaluate_route+
    better()로 검증한 뒤에만 채택하는 것과 동일하게, 여기서도 ALNS 결과가 원래 구축 해보다
    실제로 더 나을 때만(better()) 교체한다.

    better()만으로는 부족하다: better()는 feasible/repeated_edge_ratio/distance_error_m만
    비교하고 경유지 최소거리는 아예 모른다. repair 연산은 알고리즘 특성상 pool_nodes
    전체(거리 적합도만 봄, 방위각·최소거리 무관)에서 후보를 끌어오므로, ALNS가 골라온
    경유지 순서가 better()로는 이겨도 최소거리 조건을 어길 수 있다 — 2026-08-30 다중 조건
    검증(target_km=5.0)에서 30건 중 3건이 위반됐다(그중 2건은 feasible로 최종 채택까지 됨,
    overlap_ratio 0.60짜리 포함). 그래서 better() 비교 전에 최소거리부터 별도로 검증한다
    (결과 경유지 순서의 모든 연속 쌍을 검사) — 구축 단계·Local/VND/VNS는
    _rank_next_waypoint_candidates가 이 조건을 후보 생성 단계에서 이미 걸러 구조적으로
    위반이 불가능하지만, ALNS는 repair가 그 랭킹 함수를 거치지 않으므로 사후 검증이
    반드시 필요하다."""
    alns_candidates, cost_fn = _alns_adapter(G, pool_result, start_node, stats)
    alns_config = _alns_config(target_m, cfg, rng, options)

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
        _record_pending(stats, None, False, "search_failed")
        return route

    if stats is not None:
        stats.record(result)

    new_waypoints = list(result.best.waypoint_ids)
    if new_waypoints == route.waypoints:
        _record_pending(stats, result, False, "unchanged")
        return route  # ALNS가 개선하지 못함 — 불필요한 재연결 생략

    if cfg.min_waypoint_separation_ratio:
        for a, b in zip(new_waypoints, new_waypoints[1:]):
            pair_m = cost_fn(a, b)
            if not is_waypoint_pair_separated(pair_m, target_m, cfg):
                logger.debug(
                    "ALNS 결과가 경유지 최소거리 조건을 위반해 기각합니다: %.1fm < %.1fm",
                    pair_m, target_m * cfg.min_waypoint_separation_ratio,
                )
                _record_pending(stats, result, False, "separation_violation")
                return route

    improved = BuildCycleRoute(
        G, cost_cache.astar_path, start_node, new_waypoints, cost_context=cost_cache.cost_context,
    )
    if improved is None:
        _record_pending(stats, result, False, "rebuild_failed")
        return route

    tolerance = target_m * cfg.distance_tolerance_ratio
    improved_obj = evaluate_route(improved, target_m, tolerance)
    route_obj = evaluate_route(route, target_m, tolerance)
    accepted = better(improved_obj, route_obj)
    _record_pending(stats, result, accepted, "accepted" if accepted else "not_better",
                    decided_by=_decisive_key(improved_obj, route_obj))
    return improved if accepted else route  # 기각 시 원래 구축 해 유지


def shared_refinement_defaults() -> dict[str, dict[str, Any]]:
    """정제별 공용 기본값(알고리즘별 확정값이 없을 때 실제로 쓰이는 값)을 실행 메타데이터에
    남기기 위한 단일 창구다(2026-09-16).

    벤치마크 CSV의 행만 보고는 어떤 상한·반복 수로 돈 결과인지 알 수 없다 — 노브는 결과
    컬럼에 들어가지 않고, 러너가 남기던 algorithm_defaults()는 공용 기본값과 달라진
    알고리즘만 적기 때문이다. 그래서 이 모듈의 상수가 바뀌면(ex) _MAX_ITERATIONS 도입)
    과거 CSV와 새 CSV를 구분할 근거가 사라진다.

    호출 문맥에서 정해지는 값은 담지 않는다 — ALNS의 start_temperature_m(target_m 비례),
    candidate_limit(cfg.rcl_size), seed(호출마다 rng에서 새로 뽑음)는 _alns_config()가
    매번 계산하므로 고정값이 아니다. 키는 OPTIONS_AWARE_REFINEMENTS와 같아야 한다 —
    주입으로 덮어쓸 수 있는 노브가 곧 기록해야 할 기본값이다."""
    return {
        "vns": {
            "max_shake_level": _MAX_SHAKE_LEVEL,
            "max_iterations": _MAX_ITERATIONS,
        },
        "alns": {
            "iterations": _ALNS_ITERATIONS,
            "removal_fraction": _ALNS_REMOVAL_FRACTION,
            "cooling_rate": _ALNS_COOLING_RATE,
            "segment_length": _ALNS_SEGMENT_LENGTH,
            "reaction_factor": _ALNS_REACTION_FACTOR,
            "max_cost_calls": _ALNS_MAX_COST_CALLS,
        },
    }


REFINEMENT_REGISTRY = {
    "none": none,
    "local": local,
    "vnd": vnd,
    "vns": vns,
    "alns": alns,
}

# options를 실제로 해석하는 정제. 나머지는 시그니처상 받기만 하고 본문에서 쓰지 않으므로,
# 조립 계층(waypoint_engine_assembly.py)이 이 집합으로 "조용히 무시되는 주입"을 막는다 —
# 설정을 바꿨는데 결과가 그대로인 상황은 스윕 중 가장 찾기 어려운 실수다.
#
# 새 정제에 노브를 열게 되면, 해당 함수 본문이 options를 읽도록 고친 뒤 여기에 이름을
# 추가한다. 이 집합이 "지금 주입이 실제로 먹히는 정제"의 단일 기준이며, 조립 계층은 정제
# 이름을 직접 하드코딩하지 않는다.
#
# vnd(_VND_NEIGHBORHOODS)는 일부러 열지 않았다 — 3번째 이웃 AlternativeSegment가
# NotImplementedError라 만들 수 있는 조합이 (replacement,)와 (replacement,
# pair_replacement) 둘뿐인데, 앞의 것은 local()과 완전히 같은 실행이다(둘 다 같은 이웃에
# best-improvement를 개선이 멈출 때까지 반복). 즉 이미 refinement="local"로 존재하는
# 설정을 두 번째 경로로 만드는 셈이라, AlternativeSegment가 구현된 뒤에 열어야 한다.
# local()은 모듈 상수가 없어 열 것 자체가 없다(탐색 폭은 GraspConfig.rcl_size).
OPTIONS_AWARE_REFINEMENTS = frozenset({"alns", "vns"})
