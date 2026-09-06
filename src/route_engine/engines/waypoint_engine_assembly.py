"""
src/route_engine/engines/waypoint_engine_assembly.py

구축(construction) × 정제(refinement) 조립 지점("Beam/GRASP 구축·정제 조립 분리" 이슈).
기존 GRASP-Waypoint 3종(Local/VND/VNS — ALNS는 제외, 아래 참고)은 이제 이 모듈의
WaypointEngine을 각자의 (construction="grasp", refinement=...) 조합으로 고정한 얇은
래퍼다 — 로직을 옮겼을 뿐 동작은 바뀌지 않아야 한다(같은 seed·설정에서
node_ids/distance_m/repeated_edge_ratio가 리팩터 전과 일치하는지 회귀 확인 필요).

circular_grasp_waypoint_alns.py::CircularGraspWaypointAlnsEngine은 이 모듈로 옮기지
않았다 — waypoint_refinement.py 모듈 docstring의 monkeypatch 근거 참고. 이 모듈은
construction="grasp", refinement="alns" 조합도 이론상 지원하지만(REFINEMENT_REGISTRY에
"alns"가 있음), 그 경로는 waypoint_refinement.py::alns()(독립 재구현)를 타므로 기존
ALNS 엔진과는 별개의 코드 경로다.
"""

from __future__ import annotations

import logging
import random
from dataclasses import replace
from typing import Optional

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
from src.route_engine.engines.waypoint_refinement import AlnsStatsAccumulator, REFINEMENT_REGISTRY
from src.schema.route_schema import CircularRouteInput

logger = logging.getLogger(__name__)

_SEED = 42
_LABELS = {
    ("grasp", "local"): "GRASP+일반지역개선",
    ("grasp", "vnd"): "GRASP+VND",
    ("grasp", "vns"): "GRASP+VNS",
    ("beam", "local"): "Beam+일반지역개선",
    ("beam", "vnd"): "Beam+VND",
    ("beam", "vns"): "Beam+VNS",
    ("beam", "alns"): "Beam+ALNS",
}


class WaypointEngine:
    """construction({"grasp","beam"}) × refinement({"none","local","vnd","vns","alns"})
    조합 하나를 실행하는 조립 엔진. 4개 GRASP-Waypoint 엔진 클래스의 find_path()/run()
    본문에서 서로 완전히 동일했던 부분(출발 노드 탐색, 후보 풀 생성, 최선해 추적, 로그,
    좌표 변환)을 이곳 하나로 통합했다 — construction/refinement별 차이는
    CONSTRUCTION_REGISTRY/REFINEMENT_REGISTRY의 함수로만 갈린다."""

    def __init__(
        self,
        inp: CircularRouteInput,
        G: nx.Graph,
        mode: str = "distance",
        seed: int = _SEED,
        config: GraspConfig = DEFAULT_CONFIG,
        num_waypoints: Optional[int] = None,
        construction: str = "grasp",
        refinement: str = "local",
    ):
        if construction not in CONSTRUCTION_REGISTRY:
            raise ValueError(f"알 수 없는 construction: {construction!r}")
        if refinement not in REFINEMENT_REGISTRY:
            raise ValueError(f"알 수 없는 refinement: {refinement!r}")

        self.inp = inp
        # G.copy() 안 함 — 이 클래스가 부르는 것(grasp_waypoint_common.py/waypoint_pool.py/
        # PathUtils/waypoint_beam.py)은 전부 읽기 전용이고 calculate_custom_score()도 안
        # 부른다(mode="distance" 전용). 근거는 circular_grasp_waypoint_local.py::__init__
        # 주석과 동일(benchmarks/benchmark.py 모듈 docstring의 "그래프 공유·변형 규칙" 참고).
        self.G = G
        self.mode = mode
        self.seed = seed
        self.config = config if num_waypoints is None else replace(config, num_waypoints=num_waypoints)
        self.construction = construction
        self.refinement = refinement
        self.utils = PathUtils(self.G)
        self.cost_cache = _CostCache(self.G, mode=mode)
        self.pool_generator = WaypointPoolGenerator(self.G)
        self.last_selection_status: Optional[str] = None
        self.last_route: Optional[Route] = None
        self.last_geometry_metrics: Optional[RouteGeometryMetrics] = None
        self.last_alns_stats: Optional[dict] = None

    def _label(self) -> str:
        return _LABELS.get((self.construction, self.refinement), f"{self.construction}+{self.refinement}")

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

        construction_fn = CONSTRUCTION_REGISTRY[self.construction]
        refine_fn = REFINEMENT_REGISTRY[self.refinement]
        alns_stats = AlnsStatsAccumulator() if self.refinement == "alns" else None

        best_route, best_obj = None, _INFEASIBLE
        had_valid_waypoint_pair = False
        for construction_result in construction_fn(
            self.G, self.cost_cache, pool_result, start_node, target_m, self.config, rng,
        ):
            had_valid_waypoint_pair = had_valid_waypoint_pair or construction_result.had_valid_waypoint_pair
            route = construction_result.route
            if route is None:
                continue
            route = refine_fn(
                self.G, self.cost_cache, pool_result, start_node, route, target_m, self.config, rng,
                stats=alns_stats,
            )
            obj = evaluate_route(route, target_m, target_m * self.config.distance_tolerance_ratio)
            if best_route is None or better(obj, best_obj):
                best_obj, best_route = obj, route
                if alns_stats is not None:
                    alns_stats.record_winner(alns_stats.pending_result, alns_stats.pending_accepted)

        self.last_selection_status = determine_selection_status(best_route, best_obj, had_valid_waypoint_pair)
        self.last_route = best_route
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
        logger.info(
            "%s 순환 경로 선택: 노드=%d개, 거리오차=%.0fm, 반복률=%.3f, selection_status=%s, "
            "구간거리=%sm, 방위각차=%s도, 균형비=%s, 퇴화의심=%s",
            self._label(), len(best_route.node_ids), best_obj.distance_error_m, best_obj.repeated_edge_ratio,
            self.last_selection_status,
            format_optional_list(gm.segment_lengths_m), format_optional_list(gm.waypoint_angle_diffs_deg, 2),
            format_optional(gm.segment_balance_ratio, 3), gm.is_degenerate_loop,
        )
        return best_route.node_ids
