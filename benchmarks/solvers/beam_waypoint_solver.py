"""
benchmarks/solvers/beam_waypoint_solver.py

신세대 Beam(waypoint_beam.py::beam_search)을 GRASP-Waypoint 4종
(grasp_waypoint_solver.py)과 같은 조건·같은 CSV 스키마로 비교하기 위한
BasePathSolver 어댑터.

Beam은 GRASP과 달리 "경유지 선택" 하나만 순수 탐색하고, 실제 그래프 I/O(구간 A*
연결)는 하지 않는다(2026-09-03 "Beam/GRASP 공용 조립 계층" 리팩터). 그래서 이
solver가 다음 순서로 조각을 직접 엮는다:

  1) WaypointPoolGenerator.build_pool() — GRASP과 동일한 후보 풀(p1 기준 cutoff SSSP)
  2) waypoint_pool_beam_adapter.py — 위 풀을 beam_search가 요구하는
     candidates/cost 형태로 변환
  3) beam_search() — GRASP의 방향 다양성 페널티(아래 "방향 다양성 랭킹" 참고)를
     rank_penalty로 받아 반영한 거리 기준으로 beam_width개까지 탐색한다(waypoint_beam.py의
     tolerance_ratio/evaluate_route는 여기서 쓰지 않는다 — 아래 "재통행 인식 평가 방향" 참고)
  4) build_cycle_route() — 각 조합을 실제 A*로 연결(distance 전용
     DistancePathFinder — GraspConfig/EdgeCost와 무관, waypoint_route_builder.py)
  5) evaluate_route()/better() — GRASP과 동일한 사전식 비교로 beam_width개 조합 중
     최선 선택
  6) waypoint_local_search.py::local_search() — 5)에서 고른 최선 후보 하나에, GRASP-
     Waypoint+Local 엔진(circular_grasp_waypoint_local.py)과 동일한 WaypointReplacement
     지역개선을 1회(개선이 없어질 때까지 best-improvement 반복) 적용
  7) compute_route_geometry_metrics()/determine_selection_status() — GRASP과 완전히
     같은 함수로 CSV 필드(d12/d23/d31 등)를 채움

GRASP 전용 _CostCache(engines/grasp_waypoint_common.py)는 옮기지 않는다 — 이 solver는
mode="distance"만 쓰므로 DistancePathFinder로 충분하다. local_search()가 요구하는
cost_cache 인자도 `.astar_path(a, b)`만 덕타이핑으로 호출하므로 DistancePathFinder
인스턴스를 그대로 넘길 수 있다.

재통행 인식 평가 방향(2026-09-06, "Beam 재통행 인식 평가 활성화" 이슈 재설계):
    처음에는 waypoint_beam.py::beam_search()에 tolerance_ratio/evaluate_route(waypoint_
    evaluation.py::RouteEvaluator)를 그대로 전달하는 안을 시도했다. 실제 서울 도보 그래프
    (노드 160,328개)로 실측한 결과 6개 조합(target_km 3.0/5.0 × beam_width 2/8/16) 전부
    RouteEvaluator.attach_route_metrics의 일치성 검사에서 크래시했다 — beam_search의
    cost()가 쓰는 WaypointPoolResult.distance()(p1 기준 r_max 밴드로 잘라낸 부분그래프
    안에서만 도는 근사 거리)와, RouteEvaluator가 쓰는 DistancePathFinder.astar_path()(전체
    그래프 실제 최단경로)가 서로 다른 오라클이라 값이 어긋났다(실측 사례: 근사 3559.5m vs
    실제 3321.2m, 차이 238.3m — 실제 최단경로가 r_max 밴드 밖을 지나가는 지름길이라 밴드
    제한 Dijkstra가 못 찾은 경우).

    waypoint_beam.py/waypoint_alns.py/waypoint_evaluation.py(독립 Beam·ALNS 비교 트랙,
    benchmarks/runner/waypoint_beam.py·waypoint_alns.py 전용)는 cost()와 RouteEvaluator의
    path가 둘 다 전체그래프 Dijkstra라 이 문제가 없다 — 그 트랙의 계약(tolerance_ratio,
    waypoint_count, RouteMetrics.overlap_ratio, WaypointOrder.error_m)은 그대로 두고
    건드리지 않는다.

    대신 GRASP이 이미 쓰는 구조(cutoff SSSP는 후보 순위만 싸게 매기고, 실제 채택 여부는
    항상 전체 그래프 A*로 재확인)를 그대로 재사용한다 — beam_search()는 지금처럼 순수
    거리전용으로 남기고, 그 결과 중 최종 선택된 하나에만 GRASP-Waypoint+Local 엔진의
    WaypointReplacement 지역개선을 1회 적용해 재통행을 줄인다(waypoint_local_search.py로
    분리해 두 파일이 같은 함수를 공유한다). VND/VNS/ALNS가 쓰는 WaypointPairReplacement나
    다중 재시작(grasp_iters)까지는 가져오지 않는다 — Beam의 정체성("1회 결정적 탐색")과
    GRASP("24회 재시작+지역개선")의 근본적 탐색강도 차이는 이번 변경의 범위 밖이다(이슈
    원문 ETC 명시). 1패스만으로 재통행이 완전히 안 잡히는 경우가 남을 수 있음을 알고
    있다 — Beam+VND/VNS/ALNS 조합은 별도 "구축·정제 조립 리팩터" 이슈에서 다룬다.

방향 다양성 랭킹(2026-09-06, "Beam이 다 돌아간 뒤에만 Local이 개입" 문제 진단 이후 추가):
    local_search는 beam_search가 이미 만든 best_route 하나만 다듬을 수 있어서, beam_search
    자체가 "거리는 맞지만 다 같은 방향"인 후보들만 beam_width개 뽑아버리면(실측 확인,
    2026-09-06: target_km=3.0·beam_width=8에서 8개 중 7개가 첫 경유지가 같고 둘째
    경유지들도 서로 지리적으로 뭉쳐 있어 build_cycle_route가 전부 실패) local_search가
    개입할 기회조차 없다. GRASP은 이 문제를 _rank_next_waypoint_candidates()의 방향
    다양성 페널티(직전 경유지와 각도가 0°/180°에 가까우면 벌점, 90°에 가까우면 0)로
    막는다 — beam_search()에 새로 추가한 rank_penalty 훅(waypoint_beam.py 참고)에 그
    페널티 계산(_bearing_rad/_angular_separation_rad, grasp_waypoint_common.py에서 그대로
    가져다 씀)을 그대로 연결한다. 페널티는 랭킹에만 쓰이고 실제 거리(order.distance_m)에는
    안 섞인다(rank_penalty 자체의 계약).

    waypoint_alns.py::alns_search()에는 아직 이 훅이 없다 — Beam과 ALNS의 계약을 항상
    동시에 맞출 필요는 없다는 판단(2026-09-06, 명시적 지시)에 따라 지금은 Beam만 갖는다.

최소거리 안전장치 정렬(2026-09-06, "방향은 다양한데 물리적으로 붙어있는" 후보를
방향 다양성 페널티만으로는 못 거른다는 점 확인 이후 추가):
    GRASP은 is_waypoint_pair_separated()로 직전 경유지와 실제 A* 거리가
    target_m*min_waypoint_separation_ratio(기본 20%) 미만인 후보를 랭킹에서 아예
    제외한다(하드 필터, 페널티 아님). Beam의 초기 구축(beam_search) 단계에는 이
    필터가 없어서 local_search 정제 전까지는 GRASP보다 느슨한 기준으로 후보를 고르고
    있었다 — waypoint_beam.py를 또 건드리지 않고, cost() 자체를 감싸는 것만으로
    맞춘다: beam_search는 이미 cost()가 inf를 반환하면 그 후보를 건너뛰므로(기존
    "도달 불가" 의미를 그대로 재사용), 최소거리 미만인 (직전 경유지, 후보) 쌍에
    inf를 돌려주면 새 훅 없이 동일한 하드 필터가 된다(_with_min_separation_filter
    참고). 첫 경유지 선택과 도착 폐합에는 적용하지 않는다 — GRASP도 이 두 경우엔
    필터를 안 건다.
"""

import math
from math import inf
from typing import Optional

from benchmarks.solvers.base_solver import BasePathSolver
from src.route_engine.engines.grasp_waypoint_common import (
    GraspConfig,
    RouteGeometryMetrics,
    SelectionStatus,
    _INFEASIBLE,
    _angular_separation_rad,
    _bearing_rad,
    better,
    compute_route_geometry_metrics,
    determine_selection_status,
    evaluate_route,
)
from src.route_engine.engines.waypoint_local_search import local_search
from src.route_engine.engines.waypoint_pool import WaypointPoolGenerator
from src.route_engine.waypoint_beam import beam_search
from src.route_engine.waypoint_pool_beam_adapter import (
    waypoint_pool_cost_function,
    waypoint_pool_to_beam_candidates,
)
from src.route_engine.waypoint_route_builder import DistancePathFinder, build_cycle_route

_DEFAULT_TARGET_KM = 3.0
_DEFAULT_SEED = 42
_DEFAULT_NUM_WAYPOINTS = 2  # GraspConfig.num_waypoints 기본값과 동일
_DEFAULT_BEAM_WIDTH = 8  # GraspConfig.rcl_size 기본값과 맞춘 "공정 비교" 기본값.
# 지역개선 단계(local_search)의 GraspConfig.rcl_size로도 그대로 재사용한다 — Beam의
# 탐색 폭과 지역개선의 후보 폭을 같은 값으로 맞춰 "공정 비교" 기준을 유지한다.
_DEFAULT_DISTANCE_TOLERANCE_RATIO = 0.05  # GraspConfig.distance_tolerance_ratio 기본값과 동일
_DEFAULT_MIN_WAYPOINT_SEPARATION_RATIO = 0.20  # GraspConfig.min_waypoint_separation_ratio 기본값과 동일
_DEFAULT_PAIRWISE_CACHE_ROWS = 256  # GraspConfig.pairwise_cache_rows 기본값과 동일
_DEFAULT_ANGLE_DIVERSITY_WEIGHT_M = 1500.0  # GraspConfig.angle_diversity_weight_m 기본값과 동일


def _angle_diversity_rank_penalty(graph, start_node: int, weight_m: float):
    """GRASP의 _rank_next_waypoint_candidates()와 동일한 방향 다양성 페널티를
    beam_search()의 rank_penalty 훅으로 재사용한다. a==start_node(첫 경유지 선택)면
    비교할 '직전 방향'이 없어 0을 반환한다 — GRASP과 동일하게 이 단계는 순수 거리
    적합도만 본다. weight_m이 0이면(페널티 비활성) None을 반환해 beam_search 호출부가
    rank_penalty 자체를 안 넘기게 한다."""
    if not weight_m:
        return None
    p1_data = graph.nodes[start_node]

    def penalty(a: int, b: int) -> float:
        if a == start_node:
            return 0.0
        a_data, b_data = graph.nodes[a], graph.nodes[b]
        bearing_prev = _bearing_rad(p1_data["lat"], p1_data["lon"], a_data["lat"], a_data["lon"])
        bearing_c = _bearing_rad(p1_data["lat"], p1_data["lon"], b_data["lat"], b_data["lon"])
        separation = _angular_separation_rad(bearing_prev, bearing_c)
        return weight_m * abs(math.cos(separation))

    return penalty


def _with_min_separation_filter(cost, start_node: int, min_separation_m: float):
    """GRASP의 is_waypoint_pair_separated()와 동일한 하드 필터를 beam_search()의
    cost()에 얹는다. waypoint_beam.py는 건드리지 않는다 — beam_search가 이미 cost()의
    inf를 '도달 불가'로 보고 그 후보를 건너뛰므로, 그 의미를 그대로 재사용한다. 첫
    경유지 선택(a==start_node) 또는 도착 폐합(b==start_node)에는 적용하지 않는다 —
    GRASP도 이 두 경우엔 필터를 걸지 않는다. min_separation_m이 0이면(비율 0) 그대로
    통과시켜 필터를 끈다."""
    if not min_separation_m:
        return cost

    def wrapped(a: int, b: int) -> float:
        base = cost(a, b)
        if a == start_node or b == start_node or base == inf:
            return base
        return base if base >= min_separation_m else inf

    return wrapped


def _segment_metrics_from_geometry(
    gm: Optional[RouteGeometryMetrics], status: Optional[str], min_separation_m: float,
) -> dict:
    """grasp_waypoint_solver.py::_segment_metrics()와 같은 키 구성을 만든다. GRASP은
    engine 객체에서 last_geometry_metrics/last_selection_status/config를 읽지만,
    Beam은 이 solver 안에서 직접 계산하므로 그 값들을 인자로 받는다."""

    def r(value, digits=4):
        return round(value, digits) if value is not None else None

    if gm is None:
        gm = RouteGeometryMetrics(None, None, None, None, None, False)

    segments = gm.segment_lengths_m
    angles = gm.waypoint_angle_diffs_deg

    return {
        "selection_status": status,
        "feasible": status == SelectionStatus.FEASIBLE,
        "segment_p1_p2_m": r(segments[0]) if segments else None,
        "segment_p2_p3_m": r(segments[1]) if segments and len(segments) > 1 else None,
        "segment_p3_p1_m": r(segments[-1]) if segments else None,
        "waypoint_separation_m": r(gm.waypoint_separation_m),
        "min_waypoint_separation_m": round(min_separation_m, 4),
        "repeated_edge_ratio": r(gm.repeated_edge_ratio, 4),
        "waypoint_angle_diff_deg": r(angles[0], 2) if angles else None,
        "segment_balance_ratio": r(gm.segment_balance_ratio, 4),
        "is_degenerate_loop": gm.is_degenerate_loop,
    }


class CircularBeamWaypointSolver(BasePathSolver):
    def __init__(self, name: str = "Beam-Waypoint", seed: int = _DEFAULT_SEED):
        super().__init__(name)
        self.seed = seed

    def solve(self, graph, start_node, target_node, params: dict) -> dict:
        target_km = params.get("target_km") or _DEFAULT_TARGET_KM
        target_m = target_km * 1000
        num_waypoints = params.get("num_waypoints", _DEFAULT_NUM_WAYPOINTS)
        beam_width = params.get("beam_width", _DEFAULT_BEAM_WIDTH)
        distance_tolerance_ratio = params.get("distance_tolerance_ratio", _DEFAULT_DISTANCE_TOLERANCE_RATIO)
        min_waypoint_separation_ratio = params.get(
            "min_waypoint_separation_ratio", _DEFAULT_MIN_WAYPOINT_SEPARATION_RATIO
        )
        pairwise_cache_rows = params.get("pairwise_cache_rows", _DEFAULT_PAIRWISE_CACHE_ROWS)
        angle_diversity_weight_m = params.get("angle_diversity_weight_m", _DEFAULT_ANGLE_DIVERSITY_WEIGHT_M)
        min_separation_m = target_m * min_waypoint_separation_ratio

        path_finder = DistancePathFinder(graph)

        start_data = graph.nodes[start_node]
        pool_result = WaypointPoolGenerator(graph).build_pool(
            start_data.get("lat", 0.0), start_data.get("lon", 0.0), target_km,
            pairwise_cache_rows=pairwise_cache_rows,
        )

        if pool_result is None or len(pool_result.pool_nodes) < num_waypoints:
            # grasp-wp-* solver(_circular_engine_common.py::run_circular_engine_distance_only)와
            # 동일한 실패 규약 — 유효한 순환 경로를 못 만들면 여기서 raise해 벤치마크
            # 하네스가 status="failed" 행으로 처리하게 한다. cost=0.0짜리 가짜 "ok" 행을
            # 만들면 GRASP과 CSV 상에서 비교가 어긋난다(실측 회귀로 확인, 2026-09-05).
            raise ValueError("경로 생성 실패: 유효한 순환 경로를 찾지 못했습니다 (NO_PATH)")

        candidates = waypoint_pool_to_beam_candidates(graph, pool_result)
        cost = waypoint_pool_cost_function(pool_result, start_node)
        cost = _with_min_separation_filter(cost, start_node, min_separation_m)

        result = beam_search(
            candidates=candidates,
            cost=cost,
            start_id=start_node,
            end_id=start_node,
            target_m=target_m,
            waypoint_count=num_waypoints,
            beam_width=beam_width,
            rank_penalty=_angle_diversity_rank_penalty(graph, start_node, angle_diversity_weight_m),
        )
        had_valid_waypoint_pair = bool(result.orders)

        best_route, best_obj = None, _INFEASIBLE
        for order in result.orders:
            route = build_cycle_route(graph, path_finder.astar_path, start_node, order.waypoint_ids)
            if route is None:
                continue
            obj = evaluate_route(route, target_m, target_m * distance_tolerance_ratio)
            if best_route is None or better(obj, best_obj):
                best_obj, best_route = obj, route

        if best_route is None:
            # 위와 동일한 실패 규약 — beam_search가 조합(들)은 찾았지만(had_valid_waypoint_pair)
            # 그중 어느 것도 실제 A* 연결·prune_dead_ends를 통과하지 못한 경우
            # (예: 두 후보가 사실상 같은 도로의 왕복이라 pruning으로 통째로 사라짐).
            raise ValueError("경로 생성 실패: 유효한 순환 경로를 찾지 못했습니다 (NO_PATH)")

        grasp_cfg = GraspConfig(
            distance_tolerance_ratio=distance_tolerance_ratio,
            min_waypoint_separation_ratio=min_waypoint_separation_ratio,
            pairwise_cache_rows=pairwise_cache_rows,
            num_waypoints=num_waypoints,
            rcl_size=beam_width,
            angle_diversity_weight_m=angle_diversity_weight_m,
        )
        best_route, best_obj = local_search(
            graph, path_finder, pool_result, start_node, best_route, target_m, grasp_cfg,
        )

        selection_status = determine_selection_status(best_route, best_obj, had_valid_waypoint_pair)
        geometry_metrics = compute_route_geometry_metrics(
            graph, path_finder.astar_path, start_node, best_route, target_m
        )

        return {
            "paths": [best_route.node_ids],
            "cost": best_route.distance_m,
            "overlap_ratio": 0.0,  # grasp-wp-* solver와 동일하게 0.0 고정 — 실측값은 repeated_edge_ratio에
            "astar_calls": path_finder.astar_calls,
            "cache_hits": path_finder.cache_hits,
            **_segment_metrics_from_geometry(geometry_metrics, selection_status, min_separation_m),
        }
