"""
src/route_engine/engines/waypoint_engine_assembly.py

구축(construction) × 정제(refinement) 조립 지점("Beam/GRASP 구축·정제 조립 분리" 이슈).
기존 GRASP-Waypoint 3종(Local/VND/VNS — ALNS는 제외, 아래 참고)은 이제 이 모듈의
WaypointEngine을 각자의 (construction="grasp", refinement=...) 조합으로 고정한 얇은
래퍼다 — 로직을 옮겼을 뿐 동작은 바뀌지 않아야 한다(같은 seed·설정에서
node_ids/distance_m/repeated_edge_ratio가 리팩터 전과 일치하는지 회귀 확인 필요).

circular_grasp_waypoint_alns.py::CircularGraspWaypointAlnsEngine도 같은 얇은 래퍼다
("ALNS 정제 로직 이중화 해소" 이슈) — 예전에는 그 엔진이 자체 _improve_with_alns()/
_AlnsStatsAccumulator를 들고 있어 정제 로직이 두 벌이었지만, 이제 GRASP+ALNS와
Beam+ALNS가 waypoint_refinement.py::alns() 하나를 공유한다.

최종 경로 1개 + 후보 2개(이슈 #443):
    MULTI_CANDIDATE_COMBOS에 속한 조합은 run()이 CANDIDATE_COUNT개의 응답을 반환한다.
    첫 번째가 최종 경로이고 나머지가 후보이며, 후보는 last_alternative_routes에도 남는다.

    "최종 경로"와 "후보"를 개념적으로 분리한 이유는 벤치마크 지표를 건드리지 않기
    위해서다. find_path()는 예전과 똑같이 최종 경로 노드열 하나만 반환하므로, 이 함수를
    쓰는 벤치마크 어댑터(benchmarks/solvers/_circular_engine_common.py::
    run_circular_engine_distance_only)와 CSV 지표는 전혀 바뀌지 않는다. 후보는 별도
    속성으로만 나간다.

    find_path()의 최선해 추적(better 순차 갱신)도 그대로다 — 후보 수집은 그 옆에서
    풀을 쌓기만 하고 승자 선택에 끼어들지 않는다. 즉 같은 seed에서 최종 경로는
    이 변경 전후로 동일하다.

candidate_feature_vectors(장기 프로필 SGD 스냅샷):
    run()이 반환하는 각 WalkRouteResponse와 같은 순서로 후보별 {"safety": 0~1, "comfort": 0~1}
    평균을 채운다. 각 값은 탐색 비용식과 같은 지표다 — safety는 1 - unsafe(안전시설 커버리지와
    사고위험 결합), comfort는 slope_score(= 1 - discomfort)의 길이 가중 평균이다
    (scoring_engine.path_feature_averages 참고). 안전/편안 특성값은 그래프 엣지 데이터로만 계산할 수 있어, 피드백이 들어오는
    시점(수 분~수 일 뒤)에는 이 요청의 그래프 상태를 재현할 수 없다 — 그래서 후보 생성 시점에
    바로 계산해 route_service가 RouteHistory.candidate_features(JSON)로 그대로 얼려 저장하고,
    피드백 처리 시점(longterm_profile_service)에는 재계산 없이 DB 값만 읽는다.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Optional, Union

import networkx as nx

from src.interfaces.schema.walk_schema import WalkMode, WalkRouteResponse, WalkRouteStatus
from src.route_engine.engines.grasp_waypoint_common import (
    DEFAULT_CONFIG,
    GraspConfig,
    Route,
    RouteGeometryMetrics,
    SelectionStatus,
    _CostCache,
    _INFEASIBLE,
    better,
    compute_route_geometry_metrics,
    determine_selection_status,
    evaluate_route,
    format_optional,
    format_optional_list,
)
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.engines.waypoint_construction import CONSTRUCTION_REGISTRY
from src.route_engine.engines.waypoint_pool import WaypointPoolGenerator
from src.route_engine.engines.waypoint_refinement import (
    AlnsStatsAccumulator,
    OPTIONS_AWARE_REFINEMENTS,
    REFINEMENT_REGISTRY,
)
from src.route_engine.scoring.scoring_engine import WeightedEdgeCost, path_feature_averages
from src.schema.route_schema import CircularRouteInput, OnewayRouteInput

logger = logging.getLogger(__name__)

_SEED = 42
_LABELS = {
    ("grasp", "local"): "GRASP+일반지역개선",
    ("grasp", "vnd"): "GRASP+VND",
    ("grasp", "vns"): "GRASP+VNS",
    ("grasp", "alns"): "GRASP+ALNS",
    ("beam", "local"): "Beam+일반지역개선",
    ("beam", "vnd"): "Beam+VND",
    ("beam", "vns"): "Beam+VNS",
    ("beam", "alns"): "Beam+ALNS",
}

CANDIDATE_COUNT = 3
# 다중 후보 조합이 반환하는 경로 수(최종 경로 1개 + 후보 2개). 사용자에게 3개를 보여주고,
# 그 3개의 가중치 평균을 프로필에 반영하기 위한 표본 수다.

MULTI_CANDIDATE_COMBOS = frozenset({("grasp", "local"), ("grasp", "alns")})
# 후보를 3개까지 내는 (construction, refinement) 조합. 나머지는 지금까지처럼 최종 경로
# 1개만 반환한다 — 후보를 만들 원천이 없기 때문이다(2026-09-17 실측, seed 42, 벤치 fixture
# 160,328노드, target_km=3.0·N=2에서 정제 후 서로 다른 경로 수):
#   grasp+alns 18~21개 / grasp+local 2~8개 / grasp+vnd 1~2개 / grasp+vns 2~7개 / beam+* 1개
# VND·VNS는 결정적 단조 하강이라 서로 다른 구축 결과 24개가 같은 지역 최적해로 수렴하고
# (refine_changed는 22~24로 정제 자체는 매번 작동한다), beam_construction()은 애초에
# ConstructionResult를 1개만 yield한다. 반면 ALNS는 무작위성이 있고 원본을 그대로 두는
# 경우가 많아(24개 중 4~12개만 변경) 구축 단계의 다양성이 살아남는다.
#
# 조합을 늘리려면 이 집합만 고치면 된다. 래퍼가 아니라 모듈 상수에 둔 이유는, 벤치마크가
# 래퍼를 거치지 않고 WaypointEngine을 직접 만드는 경로가 있어서다
# (benchmarks/solvers/beam_waypoint_refinement_solver.py) — 진입점마다 동작이 갈리면 안 된다.


class WaypointEngine:
    """construction({"grasp","beam"}) × refinement({"none","local","vnd","vns","alns"})
    조합 하나를 실행하는 조립 엔진. 4개 GRASP-Waypoint 엔진 클래스의 find_path()/run()
    본문에서 서로 완전히 동일했던 부분(출발 노드 탐색, 후보 풀 생성, 최선해 추적, 로그,
    좌표 변환)을 이곳 하나로 통합했다 — construction/refinement별 차이는
    CONSTRUCTION_REGISTRY/REFINEMENT_REGISTRY의 함수로만 갈린다.

    순환/편도 겸용(2026-09-20, #498 확장): inp가 OnewayRouteInput(end_lat/end_lon 보유)이면
    편도, CircularRouteInput이면 순환으로 자동 판별한다(__init__의 self._walk_mode). 편도는
    도착 노드를 추가로 찾고, 후보 풀을 build_pool_two_point로 만들고, construction_fn/
    refine_fn 전부에 end_node를 그대로 흘려보낸다 — construction/refinement 각 함수는
    end_node=None(기본값)이면 지금까지와 동일하게 동작한다. Circular*Engine 4종과
    OnewayGraspWaypointAlnsEngine은 각자의 입력 스키마만 넘기는 얇은 래퍼일 뿐, 이 판별
    로직 자체는 여기 한 곳에만 있다."""

    def __init__(
        self,
        inp: Union[CircularRouteInput, OnewayRouteInput],
        G: nx.Graph,
        mode: str = "distance",
        seed: int = _SEED,
        config: GraspConfig = DEFAULT_CONFIG,
        num_waypoints: Optional[int] = None,
        construction: str = "grasp",
        refinement: str = "local",
        refinement_options: Optional[Mapping[str, Any]] = None,
        cost_context: Optional[WeightedEdgeCost] = None,
    ):
        if construction not in CONSTRUCTION_REGISTRY:
            raise ValueError(f"알 수 없는 construction: {construction!r}")
        if refinement not in REFINEMENT_REGISTRY:
            raise ValueError(f"알 수 없는 refinement: {refinement!r}")
        if refinement_options and refinement not in OPTIONS_AWARE_REFINEMENTS:
            # find_path()는 refinement 종류와 무관하게 options를 넘기지만, 실제로 그것을
            # 읽는 정제는 OPTIONS_AWARE_REFINEMENTS뿐이다. 나머지에 넘기면 값이 조용히
            # 무시돼 "노브를 바꿨는데 결과가 그대로"가 되므로 생성 시점에 막는다.
            # (ex) 스윕 스크립트가 beam×vns 조합에 alns 노브를 실어 보내는 실수)
            raise ValueError(
                f"refinement={refinement!r}는 아직 options를 해석하지 않습니다 — "
                f"현재 주입 가능한 정제: {sorted(OPTIONS_AWARE_REFINEMENTS)}"
            )

        self.inp = inp
        # 편도(OnewayRouteInput) 여부는 end_lat 필드 존재로 판별한다 — CircularRouteInput은
        # 이 필드가 아예 없다(build_pool_two_point 분기 판별과 같은 방식, 2026-09-20, #498
        # 확장). 생성자에 별도 walk_mode 인자를 두지 않고 입력 스키마 모양만으로 자동
        # 판별한다 — Circular*Engine/OnewayGraspWaypointAlnsEngine 래퍼가 각자의 입력
        # 스키마만 넘기면 나머지는 이 클래스가 알아서 처리한다.
        self._walk_mode = WalkMode.ONEWAY_RANDOM if getattr(inp, "end_lat", None) is not None else WalkMode.CIRCULAR_RANDOM
        # G.copy() 안 함 — 이 클래스가 부르는 것(grasp_waypoint_common.py/waypoint_pool.py/
        # PathUtils/waypoint_beam.py)은 전부 읽기 전용이다. cost_context(WeightedEdgeCost)도
        # 엣지 속성을 읽기만 하고 그래프에 쓰지 않으므로(#462) 이 전제는 그대로 유지된다.
        # 근거는 benchmarks/benchmark.py 모듈 docstring의 "그래프 공유·변형 규칙" 참고.
        self.G = G
        self.mode = mode
        self.seed = seed
        self.config = config if num_waypoints is None else replace(config, num_waypoints=num_waypoints)
        self.construction = construction
        self.refinement = refinement
        # 정제별 하이퍼파라미터 주입구(waypoint_refinement.py 모듈 docstring 참고).
        # 현재 이 값을 읽는 정제는 alns()뿐이며, ALNSConfig 필드 이름을 키로 하는 부분
        # override 매핑이다 — 나머지 정제는 받되 무시한다.
        self.refinement_options = refinement_options
        self.utils = PathUtils(self.G)
        # cost_context가 있으면 구축·정제 전체의 구간 연결(A*)이 가중 비용을 쓴다(#462).
        # ALNS의 destroy-repair 자체는 pool_result.distance()만 보고 경유지를 고르므로
        # 영향받지 않는다 — 바뀌는 건 확정된 경유지를 실제 도로로 잇는 A*뿐이다.
        self.cost_context = cost_context
        self.cost_cache = _CostCache(self.G, mode=mode, cost_context=cost_context)
        self.pool_generator = WaypointPoolGenerator(self.G)
        self.last_selection_status: Optional[str] = None
        self.last_route: Optional[Route] = None
        self.last_alternative_routes: list[Route] = []
        # 최종 경로(last_route)를 **제외한** 후보. MULTI_CANDIDATE_COMBOS에 속하고 경로
        # 생성에 성공했을 때만 CANDIDATE_COUNT-1개가 채워지고, 그 외에는 빈 목록이다.
        # 벤치마크는 이 값을 읽지 않는다 — CSV 지표는 계속 최종 경로 하나만 본다.
        self.last_geometry_metrics: Optional[RouteGeometryMetrics] = None
        self.last_alns_stats: Optional[dict] = None
        self.last_pool_result = None  # 경유지 풀 pairwise 캐시 히트율 진단용(신규)
        # 장기 프로필 SGD의 X_R 입력 — 후보별 {"safety": 0~1, "comfort": 0~1} 평균(run()의
        # 반환 순서와 동일). route_service가 RouteHistory.candidate_features로 그대로
        # 영속화한다. MULTI_CANDIDATE_COMBOS가 아닌 조합은 run()이 최종 경로 1개만
        # 반환하므로 이 리스트도 길이 1이다.
        self.candidate_feature_vectors: list[dict[str, float]] = []

    def _label(self) -> str:
        return _LABELS.get((self.construction, self.refinement), f"{self.construction}+{self.refinement}")

    def _collect_alternatives(self, candidate_pool: list[tuple], best_route: Optional[Route]) -> list[Route]:
        """최종 경로를 제외한 후보 CANDIDATE_COUNT-1개를 품질 순으로 고른다.

        best_route를 결과에 넣지 않고 처음부터 제외한 뒤 run()이 맨 앞에 붙이므로,
        "첫 번째는 항상 최종 경로"가 정렬 결과와 무관하게 성립한다(정렬 1순위가 순차
        갱신 승자와 같다는 성질에 기대지 않는다 — 실측으로는 일치하지만, 계약을 성질에
        의존시키지 않는다).

        정렬은 안정 정렬이라 사전식 키가 같은 해끼리는 구축 반복 순서가 유지된다 —
        같은 seed에서 결과가 재현된다.

        중복은 node_ids 완전 일치로만 판정한다. 그래도 CANDIDATE_COUNT-1개를 못 채우면
        최선해를 복제해 채운다 — 이 경로는 "항상 3개" 계약을 지키기 위한 마감이며,
        실측상 grasp+local 40조건 중 2건(남산 1km·북한산 3km)에서만 발동하고
        grasp+alns에서는 관측되지 않았다(2026-09-17, seed 42).
        """
        if best_route is None or (self.construction, self.refinement) not in MULTI_CANDIDATE_COMBOS:
            return []

        wanted = CANDIDATE_COUNT - 1
        seen = {tuple(best_route.node_ids)}
        alternatives: list[Route] = []
        for _, route in sorted(candidate_pool, key=lambda item: item[0].sort_key()):
            key = tuple(route.node_ids)
            if key in seen:
                continue
            seen.add(key)
            alternatives.append(route)
            if len(alternatives) == wanted:
                break

        padded = wanted - len(alternatives)
        if padded:
            logger.info("%s 후보가 %d개 모자라 최종 경로를 복제해 채웁니다.", self._label(), padded)
            alternatives.extend([best_route] * padded)
        return alternatives

    def run(self) -> list[WalkRouteResponse]:
        logger.info(
            "%s(경유지 선택) 경로 생성 엔진을 시작합니다: target_km=%s, mode=%s",
            self._label(), self.inp.target_km, self.mode,
        )
        start = self.utils.find_nearest_node(self.inp.start_lat, self.inp.start_lon)
        if start is None:
            logger.warning("출발 노드를 찾지 못했습니다.")
            return [WalkRouteResponse(
                status=WalkRouteStatus.NO_NEAREST_START_NODE,
                mode=self._walk_mode, coordinates=[], total_km=0.0,
            )]

        end: Optional[int] = None
        if self._walk_mode == WalkMode.ONEWAY_RANDOM:
            end = self.utils.find_nearest_node(self.inp.end_lat, self.inp.end_lon)
            if end is None:
                logger.warning("도착 노드를 찾지 못했습니다.")
                return [WalkRouteResponse(
                    status=WalkRouteStatus.NO_NEAREST_END_NODE,
                    mode=self._walk_mode, coordinates=[], total_km=0.0,
                )]

        nodes = self.find_path(start, self.inp.target_km or 3.0, end_node=end)
        if not nodes or len(nodes) < 2:
            logger.warning("경로가 비어 있습니다.")
            return [WalkRouteResponse(
                status=WalkRouteStatus.NO_PATH,
                mode=self._walk_mode, coordinates=[], total_km=0.0,
            )]

        # 첫 번째가 항상 최종 경로다. 후보가 있는 조합이면 그 뒤에 후보를 붙여
        # CANDIDATE_COUNT개를 반환하고, 없으면 지금까지처럼 1개만 반환한다.
        # 실패 상태(위 NO_NEAREST_START_NODE/NO_PATH)는 후보 자체가 없으므로 항상 1개다.
        self.candidate_feature_vectors = []  # 같은 엔진으로 두 번 호출해도 이전 값이 새지 않게 한다
        responses = [self._to_response(nodes)]
        responses.extend(self._to_response(route.node_ids) for route in self.last_alternative_routes)
        return responses

    def _to_response(self, node_ids: list[int]) -> WalkRouteResponse:
        """노드열 하나를 응답으로 변환한다(왕복 가지 제거 -> 좌표 -> 총거리).
        최종 경로와 후보가 완전히 같은 기준으로 변환되도록 한 곳에 모았다."""
        pruned = self.utils.prune_dead_ends(node_ids)
        coords = self.utils.extract_coordinates(pruned)
        total_km = round(self.utils.calc_distance(pruned) / 1000, 2)
        # responses와 같은 순서로 candidate_feature_vectors를 쌓는다(route_service 계약).
        self.candidate_feature_vectors.append(path_feature_averages(self.G, pruned))
        return WalkRouteResponse(
            status=WalkRouteStatus.SUCCESS if coords else WalkRouteStatus.NO_PATH,
            mode=self._walk_mode, coordinates=coords, total_km=total_km,
        )

    def find_path(self, start_node: int, target_km: float = 3.0, end_node: Optional[int] = None) -> list[int]:
        """end_node(편도 지원, 2026-09-20, #498 확장): None이면(기본값) 기존 순환 동작과
        완전히 동일하다(출발지 중심 build_pool, 구축·정제 전부 start_node로 복귀). end_node를
        넘기면 출발지·도착지 두 점 기준 풀(build_pool_two_point)을 만들고, 구축·정제 전부에
        end_node를 그대로 흘려보내 편도 우회 경로를 만든다."""
        target_m = target_km * 1000
        rng = random.Random(self.seed)
        self.last_alternative_routes = []  # 같은 엔진으로 두 번 호출해도 이전 후보가 새지 않게 한다

        start_data = self.G.nodes[start_node]
        if end_node is not None:
            end_data = self.G.nodes[end_node]
            pool_result = self.pool_generator.build_pool_two_point(
                start_data.get("lat", 0.0), start_data.get("lon", 0.0),
                end_data.get("lat", 0.0), end_data.get("lon", 0.0), target_km,
                pairwise_cache_rows=self.config.pairwise_cache_rows,
            )
        else:
            pool_result = self.pool_generator.build_pool(
                start_data.get("lat", 0.0), start_data.get("lon", 0.0), target_km,
                pairwise_cache_rows=self.config.pairwise_cache_rows,
            )
        self.last_pool_result = pool_result  # None이어도 그대로 저장(풀 생성 실패 표시)
        if pool_result is None or not pool_result.pool_nodes:
            logger.warning("경유지 후보 풀을 만들지 못했습니다.")
            self.last_selection_status = SelectionStatus.NO_VALID_WAYPOINT_PAIR
            return [start_node]

        construction_fn = CONSTRUCTION_REGISTRY[self.construction]
        refine_fn = REFINEMENT_REGISTRY[self.refinement]
        alns_stats = AlnsStatsAccumulator() if self.refinement == "alns" else None

        # 후보를 낼 조합에서만 풀을 쌓는다. 최선해 추적(아래 better 비교)은 조합과 무관하게
        # 그대로라, 이 수집이 최종 경로 선택에 끼어들지 않는다.
        collect_candidates = (self.construction, self.refinement) in MULTI_CANDIDATE_COMBOS
        candidate_pool: list[tuple] = []  # [(RouteObjective, Route), ...] 구축 반복 순서대로

        best_route, best_obj = None, _INFEASIBLE
        had_valid_waypoint_pair = False
        for construction_result in construction_fn(
            self.G, self.cost_cache, pool_result, start_node, target_m, self.config, rng,
            end_node=end_node,
        ):
            had_valid_waypoint_pair = had_valid_waypoint_pair or construction_result.had_valid_waypoint_pair
            route = construction_result.route
            if route is None:
                continue
            route = refine_fn(
                self.G, self.cost_cache, pool_result, start_node, route, target_m, self.config, rng,
                stats=alns_stats, options=self.refinement_options, end_node=end_node,
            )
            obj = evaluate_route(route, target_m, target_m * self.config.distance_tolerance_ratio)
            if collect_candidates:
                candidate_pool.append((obj, route))
            if best_route is None or better(obj, best_obj):
                best_obj, best_route = obj, route
                if alns_stats is not None:
                    alns_stats.record_winner(alns_stats.pending_result, alns_stats.pending_accepted,
                                             alns_stats.pending_outcome)

        self.last_selection_status = determine_selection_status(best_route, best_obj, had_valid_waypoint_pair)
        self.last_route = best_route
        self.last_alternative_routes = self._collect_alternatives(candidate_pool, best_route)
        self.last_alns_stats = alns_stats.snapshot() if alns_stats is not None else None
        self.last_geometry_metrics = compute_route_geometry_metrics(
            self.G, self.cost_cache.astar_path, start_node, best_route, target_m,
        )

        if best_route is None:
            logger.warning(
                "%s 후보가 비어 출발 노드만 반환합니다. selection_status=%s",
                self._label(), self.last_selection_status,
            )
            return [start_node]

        gm = self.last_geometry_metrics
        if gm.prune_diagnostics is not None:
            # 겹침 제거 로직을 겹침 기준으로 바꿀지·뺄지 판단하기 위한 계측(2026-09-09).
            # clean은 재통행이 전혀 없는데도 잘려나간 구간이다 — 기준을 바꾸면 살아남는다.
            pd = gm.prune_diagnostics
            logger.info(
                "%s 가지치기 내역: 구간=%d개(%.0fm), 그중 재통행0=%d개(%.0fm), "
                "경유지 소실=재통행0 %d개 / 재통행 %d개",
                self._label(), pd.branch_count, pd.branch_length_m,
                pd.clean_branch_count, pd.clean_branch_length_m,
                pd.waypoints_lost_clean, pd.waypoints_lost_repeated,
            )
        logger.info(
            "%s %s 경로 선택: 노드=%d개, 거리오차=%.0fm, 반복률=%.3f, selection_status=%s, "
            "구간거리=%sm, 방위각차=%s도, 균형비=%s, 퇴화의심=%s, 실효경유지=%d/%d",
            self._label(), "편도" if self._walk_mode == WalkMode.ONEWAY_RANDOM else "순환",
            len(best_route.node_ids), best_obj.distance_error_m, best_obj.repeated_edge_ratio,
            self.last_selection_status,
            format_optional_list(gm.segment_lengths_m), format_optional_list(gm.waypoint_angle_diffs_deg, 2),
            format_optional(gm.segment_balance_ratio, 3), gm.is_degenerate_loop,
            best_route.effective_waypoint_count, len(best_route.waypoints),
        )
        return best_route.node_ids
