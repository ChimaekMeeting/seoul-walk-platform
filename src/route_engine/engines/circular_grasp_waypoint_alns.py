"""
src/route_engine/engines/circular_grasp_waypoint_alns.py

(버전 D) GRASP + ALNS — 비교/벤치마크용 신규 구현. 팀원이 구현한 독립 ALNS
(src/route_engine/waypoint_alns.py::alns_search, 2026-08-30 pull)를 지역탐색 단계로
그대로 재사용한다(중복 구현 금지). 기존 circular_grasp.py/grasp_solver.py, 그리고
이미 존재하는 circular_alns.py::CircularAlnsEngine(엣지 단위로 경로를 직접 만드는
완전히 다른 독립 구현)는 이 작업으로 수정하지 않는다 — 이름이 비슷하지만 다른 파일이다.

경유지 후보 풀은 다른 3개 버전(Local/VND/VNS)과 동일하게 waypoint_pool.py::
WaypointPoolGenerator를 쓰고, 초기 경유지 구축도 grasp_waypoint_common.py::
construct_initial_route를 그대로 재사용한다(같은 GRASP 구축 단계 공유 — 공정 비교
조건, 다른 3개 버전과 동일한 grasp_iters/rcl_size/seed 사용). 지역탐색 단계만
VND/VNS의 이웃 탐색 대신 waypoint_alns.py의 destroy-repair ALNS로 교체한다.

waypoint_alns.py는 그래프·A*를 전혀 모르는 순수 함수(외부 후보 풀 + cost 콜백 + 초기
순서만 받음 — 2026-08-30 docs/route_engine/README.md "경유지 ALNS 독립 함수" 절 참고,
"아직 팀원 GRASP의 실제 반환 계약과 합의·연동한 것은 아니다"라고 명시돼 있어 이 파일이
그 연동을 담당한다)라, 이 파일이 NetworkX 그래프·WaypointPoolResult와 그 함수 사이의
어댑터 역할을 한다:
  - candidates: pool_result.pool_nodes를 {node_id, lat, lon} dict로 변환(_build_alns_candidates).
  - cost(a, b): pool_result.distance()를 감싸되, p1(start_node)은 pool에 없으므로
    (waypoint_pool.py 설계상 p1은 pool_nodes에서 자기 자신이라 제외됨) pool_result.
    dist_from_p1으로 별도 처리하고, 도달 불가(None)는 ALNS 계약대로 inf로 변환한다
    (_make_cost_fn).
  - ALNS가 고른 최종 경유지 순서는 추상적인 거리 합만 보장하므로, 실제 노드열은 항상
    BuildCycleRoute(A*)로 다시 만든다(다른 3개 버전과 동일한 "raw 추정치 금지, 실제
    경로 합산" 원칙 — waypoint_alns.py 자신도 "실제 도로 겹침·다양성 평가는 이 모듈의
    구현 범위가 아니다"라고 명시).

candidate_limit(=cfg.rcl_size)로 ALNS의 repair 단계가 매번 평가하는 후보 수를
Local/VND/VNS와 비슷한 규모로 제한한다 — 후보 풀 전체(target_km에 따라 수천 개)를 매
반복 평가하면 실행 시간이 감당할 수 없이 늘어난다(waypoint_alns.py 자신의 docstring도
"큰 후보 풀은 candidate_limit·max_cost_calls와 외부 거리 캐시를 사용해 계산량을
관리해야 한다"고 명시).

경유지 n개 일반화(2026-09-02): waypoint_alns.py::alns_search는 애초에
initial_ids: Sequence[int]를 받고 remove_count = ceil(len(initial_ids) * removal_fraction)로
계산하는 등 경유지 개수에 이미 무관하게 동작한다(팀원 구현이 처음부터 N-제네릭) — 이
파일의 어댑터 쪽만 route.waypoint2/waypoint3 2개 고정 접근을 route.waypoints(list)로
바꾸면 된다.
"""

import logging
import random
from dataclasses import replace
from typing import Optional

import networkx as nx

from src.interfaces.schema.walk_schema import WalkMode, WalkRouteResponse, WalkRouteStatus
from src.route_engine.engines.grasp_waypoint_common import (
    BuildCycleRoute,
    DEFAULT_CONFIG,
    GraspConfig,
    Route,
    RouteGeometryMetrics,
    SelectionStatus,
    _CostCache,
    _INFEASIBLE,
    better,
    compute_route_geometry_metrics,
    construct_initial_route,
    determine_selection_status,
    evaluate_route,
    format_optional,
    format_optional_list,
    is_waypoint_pair_separated,
)
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.engines.waypoint_pool import WaypointPoolGenerator, WaypointPoolResult
from src.route_engine.waypoint_alns import ALNSConfig, ALNSResult, alns_search
from src.schema.route_schema import CircularRouteInput

logger = logging.getLogger(__name__)

_SEED = 42

# ALNS 설정(요청서 대상 아님 — 이 엔진 자체의 비교/벤치마크용 시작값). waypoint_alns.py
# 자신의 기본값(iterations=200)을 GRASP 반복(grasp_iters=24)과 그대로 곱하면 24*200회
# destroy-repair가 되어 실행시간이 감당할 수 없이 늘어난다. 팀원 실행기
# (benchmarks/runner/waypoint_alns.py) 기본값(iterations=30)에 맞춰 GRASP 반복 1회당
# ALNS는 가볍게 개선만 담당하게 한다 — VND/VNS와 비슷한 자릿수의 실행시간을 노린 튜닝
# 시작값이며, 서비스 품질을 보장하는 값은 아니다(waypoint_alns.py 자신의 문서화 관례와
# 동일하게 명시).
_ALNS_ITERATIONS = 30
_ALNS_MAX_COST_CALLS = 3000
_ALNS_COOLING_RATE = 0.95
_ALNS_SEGMENT_LENGTH = 10
_ALNS_REACTION_FACTOR = 0.2
_ALNS_REMOVAL_FRACTION = 0.3  # cfg.num_waypoints=2(기본값)에서는 ceil(2*0.3)=1개만 제거됨
                              # (waypoint_alns.py 규칙). num_waypoints를 늘리면 제거 개수도
                              # 비례해 늘어난다(ceil(N*removal_fraction)).


class CircularGraspWaypointAlnsEngine:
    """
    GRASP으로 경유지(cfg.num_waypoints개)를 waypoint_pool.py가 만든 후보 풀 중에서
    선택해 초기 해를 만든 뒤(construct_initial_route, 다른 3개 버전과 공유), 팀원의
    독립 ALNS(waypoint_alns.py::alns_search)로 그 경유지 선택·순서를 destroy-repair
    방식으로 개선한다. ALNS는 그래프를 몰라 추상적인 (경유지 순서, 거리 합)만 반환하므로,
    최종 Route는 항상 BuildCycleRoute(A*)로 다시 만든다.
    """

    def __init__(
        self,
        inp: CircularRouteInput,
        G: nx.Graph,
        mode: str = "distance",
        seed: int = _SEED,
        config: GraspConfig = DEFAULT_CONFIG,
    ):
        self.inp = inp
        # G.copy() 안 함(2026-08-30 재검토) — grasp_waypoint_common.py/waypoint_pool.py/
        # PathUtils는 읽기 전용이고, waypoint_alns.py::alns_search는 G 자체를 받지 않으며
        # (candidates dict + cost 콜백만 받음) 구조적으로 그래프를 변형할 수 없다.
        # calculate_custom_score()도 안 부른다(mode="distance" 전용). 이유는
        # circular_grasp_waypoint_local.py::__init__ 주석 참고 — 그래프를 변형하는 코드를
        # 추가하면 이 가정이 깨지므로 다시 복사해야 한다(benchmarks/benchmark.py 모듈
        # docstring의 "그래프 공유·변형 규칙" 참고).
        self.G = G
        self.mode = mode
        self.seed = seed
        self.config = config
        self.utils = PathUtils(self.G)
        self.cost_cache = _CostCache(self.G, mode=mode)
        self.pool_generator = WaypointPoolGenerator(self.G)
        self.last_selection_status: Optional[str] = None  # 벤치마크/로그 전용(요청서 §3.6, §6)
        self.last_route: Optional[Route] = None  # 벤치마크가 구간 거리 등을 재계산할 때 씀
        self.last_alns_stats: Optional[dict] = None  # destroy/repair operator 사용 통계(아래 참고)
        self.last_geometry_metrics: Optional[RouteGeometryMetrics] = None  # 원형성 진단 지표(2026-08-30)

    def run(self) -> list[WalkRouteResponse]:
        logger.info(
            "GRASP+ALNS(경유지 선택) 경로 생성 엔진을 시작합니다: target_km=%s, mode=%s",
            self.inp.target_km, self.mode,
        )
        start = self.utils.find_nearest_node(self.inp.start_lat, self.inp.start_lon)
        if start is None:
            logger.warning("출발 노드를 찾지 못했습니다.")
            return [WalkRouteResponse(
                status=WalkRouteStatus.NO_NEAREST_START_NODE,
                mode=WalkMode.CIRCULAR_RANDOM, coordinates=[], total_km=0.0,
            )]

        nodes = self.find_path(start, self.inp.target_km or 3.0)
        if not nodes or len(nodes) < 2:
            logger.warning("경로가 비어 있습니다.")
            return [WalkRouteResponse(
                status=WalkRouteStatus.NO_PATH,
                mode=WalkMode.CIRCULAR_RANDOM, coordinates=[], total_km=0.0,
            )]

        pruned = self.utils.prune_dead_ends(nodes)
        coords = self.utils.extract_coordinates(pruned)
        total_km = round(self.utils.calc_distance(pruned) / 1000, 2)
        return [WalkRouteResponse(
            status=WalkRouteStatus.SUCCESS if coords else WalkRouteStatus.NO_PATH,
            mode=WalkMode.CIRCULAR_RANDOM, coordinates=coords, total_km=total_km,
        )]

    def find_path(self, start_node: int, target_km: float = 3.0) -> list[int]:
        target_m = target_km * 1000
        rng = random.Random(self.seed)

        start_data = self.G.nodes[start_node]
        pool_result = self.pool_generator.build_pool(
            start_data.get("lat", 0.0), start_data.get("lon", 0.0), target_km,
            pairwise_cache_rows=self.config.pairwise_cache_rows,
        )
        if pool_result is None or not pool_result.pool_nodes:
            logger.warning("경유지 후보 풀을 만들지 못했습니다.")
            self.last_selection_status = SelectionStatus.NO_VALID_WAYPOINT_PAIR
            return [start_node]

        # 풀·cost 콜백·ALNS 설정 틀은 GRASP 반복 전체가 공유한다(반복마다 다시 만들지
        # 않음 — pool_result.pool_nodes는 이번 find_path 호출 동안 바뀌지 않는다).
        alns_candidates = _build_alns_candidates(self.G, pool_result)
        cost_fn = _make_cost_fn(pool_result, start_node)
        alns_config_template = ALNSConfig(
            iterations=_ALNS_ITERATIONS,
            removal_fraction=_ALNS_REMOVAL_FRACTION,
            start_temperature_m=target_m * self.config.distance_tolerance_ratio,
            # tolerance(evaluate_route에 쓰는 target_m*distance_tolerance_ratio)와 같은
            # 스케일로 맞춘다(2026-09-03) — 이전에는 고정 150.0m 상수였는데, tolerance가
            # target_m 비례 비율로 바뀌면서 target_m=3000이 아닌 호출에서는 "같은
            # 스케일"이라는 원래 의도가 깨졌다. target_m이 이미 이 시점에 있으므로 같은
            # 식으로 그때그때 계산한다.
            cooling_rate=_ALNS_COOLING_RATE,
            segment_length=_ALNS_SEGMENT_LENGTH,
            reaction_factor=_ALNS_REACTION_FACTOR,
            candidate_limit=self.config.rcl_size,
            max_cost_calls=_ALNS_MAX_COST_CALLS,
        )

        stats = _AlnsStatsAccumulator()

        best_route, best_obj = None, _INFEASIBLE
        had_valid_waypoint_pair = False
        for _ in range(self.config.grasp_iters):
            construction = construct_initial_route(self.G, self.cost_cache, pool_result, start_node, target_m, rng, self.config)
            had_valid_waypoint_pair = had_valid_waypoint_pair or construction.had_valid_waypoint_pair
            route = construction.route
            if route is None:
                continue

            # ALNS는 alns_search() 내부에서 매번 Random(config.seed)를 새로 만든다
            # (alns_search가 외부 rng를 공유받지 않는 순수 함수 설계이기 때문 —
            # waypoint_alns.py 참고). GRASP 바깥 루프의 rng에서 매 반복 새 시드를 뽑지
            # 않고 seed를 고정해두면, initial_ids만 다를 뿐 24번의 GRASP 반복 내내 ALNS의
            # destroy-repair 난수열 자체는 완전히 동일해져 탐색 다양성이 줄어든다(실측
            # 확인, 2026-08-30) — 매 반복 rng.randrange로 새 seed를 뽑아 이 문제를 없앤다.
            alns_config = replace(alns_config_template, seed=rng.randrange(2**31))
            route, alns_accepted, alns_result = self._improve_with_alns(
                route, alns_candidates, cost_fn, start_node, alns_config, target_m,
            )
            stats.record(alns_result)

            obj = evaluate_route(route, target_m, target_m * self.config.distance_tolerance_ratio)
            if best_route is None or better(obj, best_obj):
                best_obj, best_route = obj, route
                stats.record_winner(alns_result, alns_accepted)

        self.last_selection_status = determine_selection_status(best_route, best_obj, had_valid_waypoint_pair)
        self.last_route = best_route
        self.last_alns_stats = stats.snapshot()
        self.last_geometry_metrics = compute_route_geometry_metrics(self.G, self.cost_cache, start_node, best_route, target_m)

        if best_route is None:
            logger.warning(
                "GRASP(경유지 선택, ALNS) 후보가 비어 출발 노드만 반환합니다. selection_status=%s",
                self.last_selection_status,
            )
            return [start_node]

        gm = self.last_geometry_metrics
        logger.info(
            "GRASP+ALNS 순환 경로 선택: 노드=%d개, 거리오차=%.0fm, 반복률=%.3f, selection_status=%s, "
            "구간거리=%sm, 방위각차=%s도, 균형비=%s, 퇴화의심=%s",
            len(best_route.node_ids), best_obj.distance_error_m, best_obj.repeated_edge_ratio, self.last_selection_status,
            format_optional_list(gm.segment_lengths_m), format_optional_list(gm.waypoint_angle_diffs_deg, 2),
            format_optional(gm.segment_balance_ratio, 3), gm.is_degenerate_loop,
        )
        return best_route.node_ids

    def _improve_with_alns(
        self,
        route: Route,
        alns_candidates: list[dict],
        cost_fn,
        start_node: int,
        alns_config: ALNSConfig,
        target_m: float,
    ) -> tuple[Route, bool, Optional[ALNSResult]]:
        """route.waypoints를 초기 순서로 alns_search를 1회 실행하고, 결과로 나온 경유지
        순서를 BuildCycleRoute(A*)로 다시 연결해 실제 Route를 만든다.
        (개선된 route, ALNS 결과를 실제로 채택했는지, alns_search()의 원본 반환값 —
        연산자 통계 집계용, 실패 시 None)를 반환한다.

        alns_search의 자체 수락 기준(_rank)은 distance_error_m만 본다 —
        repeated_edge_ratio도, 이 파일의 GraspConfig.angle_diversity_weight_m·
        min_waypoint_separation_ratio도 알지 못한다. 그래서 ALNS가 목표거리에는 더
        가까우면서 왕복 퇴화에 가까운(반복률 높은) 조합을 "best"로 고를 수 있다 —
        실측으로 확인됨(2026-08-30, target_km=3.0 seed=42: ALNS 결과를 그대로 쓰면
        overlap_ratio=0.40까지 나빠짐). VND/VNS가 이웃/Shake 결과를 evaluate_route+
        better()로 검증한 뒤에만 채택하는 것과 동일하게, 여기서도 ALNS 결과가 원래
        GRASP 초기 해보다 실제로 더 나을 때만(better()) 교체한다 — 그렇지 않으면
        GRASP 구축 단계가 이미 확보한 방향 다양성·최소거리 안전장치가 ALNS 한 번으로
        조용히 무효화된다.

        better()만으로는 부족하다: better()는 feasible/repeated_edge_ratio/distance_error_m만
        비교하고 경유지 최소거리는 아예 모른다. repair 연산은 알고리즘 특성상 pool_result.
        pool_nodes 전체(거리 적합도만 봄, 방위각·최소거리 무관)에서 후보를 끌어오므로,
        ALNS가 골라온 경유지 순서가 better()로는 이겨도 최소거리 조건을 어길 수 있다 —
        2026-08-30 다중 조건 검증(target_km=5.0)에서 실측으로 30건 중 3건이 위반됐다
        (그중 2건은 feasible로 최종 채택까지 됨, overlap_ratio 0.60짜리 포함). 그래서
        better() 비교 전에 최소거리부터 별도로 검증한다(경유지 n개 일반화 이후에는 결과
        경유지 순서의 모든 연속 쌍을 검사) — construct_initial_route/Local·VND·VNS는
        _rank_next_waypoint_candidates가 이 조건을 후보 생성 단계에서 이미 걸러 구조적으로
        위반이 불가능하지만, ALNS는 repair가 그 랭킹 함수를 거치지 않으므로 결과에서
        사후 검증이 반드시 필요하다."""
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
            logger.warning("ALNS 실행 실패(%s) — 개선 없이 GRASP 초기 해를 그대로 씁니다.", e)
            return route, False, None

        new_waypoints = list(result.best.waypoint_ids)
        if new_waypoints == route.waypoints:
            return route, False, result  # ALNS가 개선하지 못함 — 불필요한 재연결 생략

        if self.config.min_waypoint_separation_ratio:
            for a, b in zip(new_waypoints, new_waypoints[1:]):
                pair_m = cost_fn(a, b)
                if not is_waypoint_pair_separated(pair_m, target_m, self.config):
                    logger.debug(
                        "ALNS 결과가 경유지 최소거리 조건을 위반해 기각합니다: %.1fm < %.1fm",
                        pair_m, target_m * self.config.min_waypoint_separation_ratio,
                    )
                    return route, False, result

        improved = BuildCycleRoute(self.G, self.cost_cache, start_node, new_waypoints)
        if improved is None:
            return route, False, result

        tolerance = target_m * self.config.distance_tolerance_ratio
        if better(evaluate_route(improved, target_m, tolerance), evaluate_route(route, target_m, tolerance)):
            return improved, True, result
        return route, False, result  # ALNS 결과가 실제로는(반복률 포함) 더 나쁨 — 원래 GRASP 해 유지


class _AlnsStatsAccumulator:
    """GRASP grasp_iters회에 걸친 ALNS 호출들의 destroy/repair operator 통계를 모은다
    (요청서 §4.4/§7 "operator별 사용 횟수·개선 횟수·수락 횟수·best 개선 횟수" 대응).

    waypoint_alns.py::ALNSResult가 실제로 제공하는 값은 operator별 uses(사용 횟수)와
    호출 종료 시점의 weight(적응형 가중치 — 그 자체가 누적 보상의 이동평균이라 "얼마나
    성공적이었는지"의 대리 지표)뿐이다. operator별 개선 횟수·SA 수락 횟수는
    ALNSResult가 분리해서 주지 않는다(accepted_moves/failed_repairs는 호출 전체
    합계로만 제공됨) — 이 클래스는 모듈이 실제로 반환하는 값만 정직하게 집계하고,
    반환하지 않는 값을 추정해서 채우지 않는다."""

    def __init__(self):
        self.calls = 0
        self.total_iterations = 0
        self.total_accepted_moves = 0
        self.total_failed_repairs = 0
        self.total_cost_calls = 0
        self.destroy_uses: dict[str, int] = {}
        self.repair_uses: dict[str, int] = {}
        self.accepted_alns_calls = 0  # find_path의 best_route 갱신 시점에 ALNS 결과가 실제 채택된 횟수
        self.winner_alns_result: Optional[ALNSResult] = None
        self.winner_alns_accepted: Optional[bool] = None

    def record(self, result: Optional[ALNSResult]) -> None:
        if result is None:  # alns_search 자체가 실패(ValueError)했던 호출
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
        """best_route가 이 GRASP 반복으로 갱신될 때마다 호출 — 최종적으로 채택된 경로를
        만든(또는 시도했으나 기각된) ALNS 실행의 상세를 별도로 남긴다."""
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
            # best_route를 만든 마지막 갱신 시점의 ALNS 실행(최종 채택된 경로와 가장
            # 직접적으로 연결된 단일 실행 — winner_alns_accepted=False면 이 실행의
            # 제안은 better()에 의해 기각되고 GRASP raw 구축 해가 최종 채택됐다는 뜻).
            "winning_iteration": {
                "accepted": self.winner_alns_accepted,
                "stop_reason": winner.stop_reason if winner else None,
                "iterations": winner.iterations if winner else None,
                "accepted_moves": winner.accepted_moves if winner else None,
                "failed_repairs": winner.failed_repairs if winner else None,
                "cost_calls": winner.cost_calls if winner else None,
                "destroy_stats": (
                    [(s.name, s.uses, s.weight) for s in winner.destroy_stats] if winner else None
                ),
                "repair_stats": (
                    [(s.name, s.uses, s.weight) for s in winner.repair_stats] if winner else None
                ),
            } if winner is not None else None,
        }


def _build_alns_candidates(G: nx.Graph, pool_result: WaypointPoolResult) -> list[dict]:
    """pool_result.pool_nodes를 waypoint_alns.py가 요구하는 {node_id, lat, lon} dict
    목록으로 변환한다(WaypointCandidate 계약, src/route_engine/waypoint_types.py 참고)."""
    return [
        {"node_id": node, "lat": G.nodes[node]["lat"], "lon": G.nodes[node]["lon"]}
        for node in pool_result.pool_nodes
    ]


def _make_cost_fn(pool_result: WaypointPoolResult, start_node: int):
    """waypoint_alns.py::CostFunction 계약(대칭 거리 m, 도달 불가는 inf)에 맞춘 cost(a,b).

    p1(start_node)은 waypoint_pool.py 설계상 pool_nodes에 포함되지 않으므로(자기 자신
    이라 제외됨), pool_result.distance()에 직접 넘기면 ValueError가 난다 — p1이 관여
    하는 두 구간(start→첫 경유지, 마지막 경유지→start)은 pool_result.dist_from_p1으로
    따로 처리한다."""

    def cost(a: int, b: int) -> float:
        if a == start_node:
            return pool_result.dist_from_p1.get(b, float("inf"))
        if b == start_node:
            return pool_result.dist_from_p1.get(a, float("inf"))
        d = pool_result.distance(a, b)
        return d if d is not None else float("inf")

    return cost
