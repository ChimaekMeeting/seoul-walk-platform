import logging
from typing import List, Optional

import networkx as nx

from src.interfaces.schema.walk_schema import (
    WalkMode,
    WalkRouteResponse,
    WalkRouteStatus,
)
from src.route_engine.engines.oneway_astar import OnewayAstarEngine
from src.route_engine.engines.oneway_beam import OnewayBeamEngine
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.profiles import ScoringProfile
from src.route_engine.scoring.scoring_engine import compute_score_vector
from src.schema.route_schema import OnewayRouteInput, WaypointRouteInput, Weights

logger = logging.getLogger(__name__)

# leg_modes 값(WaypointRouteInput.WaypointLegMode)별로 재사용할 기존 편도 엔진
_LEG_ENGINES = {
    "oneway_shortest": OnewayAstarEngine,
    "oneway_random": OnewayBeamEngine,
}


class WaypointComposerEngine:
    """
    출발지 -> 경유지들 -> 목적지를 구간(leg)별로 나눠, 각 leg에 지정된 모드의
    기존 편도 엔진(OnewayAstarEngine/OnewayBeamEngine)을 순차 호출해 하나의 경로로 이어 붙인다.
    새 탐색 알고리즘을 추가하지 않고 기존 엔진을 조합만 한다.

    oneway_random leg의 OnewayBeamEngine은 다양화한 후보를 최대 3개까지 반환한다.
    모든 leg가 성공하면, leg별로 같은 인덱스(대표/2번째/3번째)끼리 짝지어 이어붙인
    "슬롯" 최대 3개를 만들고, 그중 완전히 겹치는 슬롯은 버린 뒤(예: 모든 leg가
    oneway_shortest라 애초에 대안이 없는 경우) 벡터 다양화(select_diverse_paths)로
    최종 후보를 정리해 반환한다. leg 개수와 무관하게 항상 최대 3개만 계산하므로
    leg별 후보를 전부 조합(3^legs)하지는 않는다. 일부 leg가 실패한 경우엔 다양화 없이
    기존처럼 대표 경로 1개만 이어붙여 반환한다.
    """

    def __init__(
        self,
        inp: WaypointRouteInput,
        G: nx.Graph,
        custom_weights: Optional[Weights] = None,
        profile: Optional[ScoringProfile] = None,
    ):
        self.inp            = inp
        # 그래프를 직접 mutate하지 않고 leg 엔진에 그대로 넘기기만 하므로 복사가 필요 없다.
        # 실제 mutation(예: OnewayBeamEngine의 custom_score 계산)은 그걸 하는 leg 엔진이 자체적으로 격리한다.
        self.G               = G
        self.custom_weights  = custom_weights
        self.profile         = profile
        self.mode            = WalkMode.WAYPOINT

    def run(self) -> List[WalkRouteResponse]:
        """
        경유지 반영 경로를 leg별로 생성해 하나로 이어 붙입니다.
        """
        logger.info(
            "경유지 반영 경로 생성 엔진을 시작합니다: legs=%d, leg_modes=%s",
            len(self.inp.leg_modes), self.inp.leg_modes,
        )

        # stops = [(start_lat, start_lon), (wp1.lat, wp1.lon), (wp2.lat, wp2.lon), (end_lat, end_lon)]
        stops = [
            (self.inp.start_lat, self.inp.start_lon),          # 출발지
            *[(wp.lat, wp.lon) for wp in self.inp.waypoints],  # 경유지  cf. *(unpacking)은 중첩 리스트를 풀어서 넣으라는 뜻
            (self.inp.end_lat, self.inp.end_lon),              # 목적지
        ]

        total_legs = len(self.inp.leg_modes)
        visited_nodes: set = set()  # 앞선 leg들이 지나간 노드. 다음 leg 탐색에 겹침 페널티로 반영
        # leg별로 (그 leg가 반환한 모든 후보 WalkRouteResponse, 그 후보들의 노드열)을 순서대로 쌓는다.
        leg_candidates: List[tuple] = []
        for i, mode in enumerate(self.inp.leg_modes):
            start_lat, start_lon = stops[i]
            end_lat, end_lon     = stops[i + 1]
            leg_inp = OnewayRouteInput(
                start_lat=start_lat,
                start_lon=start_lon,
                end_lat=end_lat,
                end_lon=end_lon,
                target_km=self.inp.leg_target_km[i],
            )
            engine = _LEG_ENGINES[mode](
                leg_inp, self.G, custom_weights=self.custom_weights, profile=self.profile,
                visited_nodes=visited_nodes,
            )
            leg_responses = engine.run()  # oneway_random이면 최대 3개, oneway_shortest면 1개
            leg_node_paths = engine.last_path_nodes_by_candidate
            result = leg_responses[0]  # 대표 후보 — 상태 판정·재시도 로직은 기존처럼 이걸 기준으로 한다

            # 다른 엔진들의 base_shortest 대체와 같은 패턴: 실패하면 최단 경로로 재시도
            if result.status != WalkRouteStatus.SUCCESS and mode != "oneway_shortest":
                logger.warning("leg %d(%s)에서 실패해 최단 경로로 대체합니다: status=%s",
                               i + 1, mode, result.status.value)
                engine = OnewayAstarEngine(
                    leg_inp, self.G, custom_weights=self.custom_weights, profile=self.profile,
                    visited_nodes=visited_nodes,
                )
                leg_responses  = engine.run()
                leg_node_paths = engine.last_path_nodes_by_candidate
                result = leg_responses[0]

            leg_candidates.append((leg_responses, leg_node_paths))

            logger.info("leg %d/%d 결과: mode=%s status=%s 후보수=%d",
                        i + 1, total_legs, mode, result.status.value, len(leg_responses))

            if result.status != WalkRouteStatus.SUCCESS:
                logger.warning("leg %d에서 최단 경로 대체도 실패해 이후 leg를 생략합니다: status=%s", i + 1, result.status.value)
                break

            visited_nodes.update(engine.last_path_nodes)  # 실제로 이 leg를 만든 엔진(재시도 포함)의 경로를 누적

        all_legs_succeeded = (
            len(leg_candidates) == total_legs
            and all(responses[0].status == WalkRouteStatus.SUCCESS for responses, _ in leg_candidates)
        )

        # 일부 leg가 실패한 경우엔 다양화 없이 대표 경로 1개만 이어붙여 기존과 동일하게 반환한다.
        if not all_legs_succeeded:
            leg_results = [responses[0] for responses, _ in leg_candidates]
            return [self._stitch(leg_results, total_legs)]

        # 모든 leg가 성공한 경우에만 최대 3개까지 다양화한 전체 경로를 만든다.
        vector_lookup = compute_score_vector(self.G)
        seen_node_paths: List[list] = []
        diversity_candidates: List[tuple] = []  # [(score_vector, WalkRouteResponse), ...]
        for slot in range(3):
            node_path = self._concat_leg_nodes([
                node_paths[min(slot, len(node_paths) - 1)] for _, node_paths in leg_candidates
            ])
            if node_path in seen_node_paths:
                continue  # 이 leg 조합으로는 이미 나온 경로와 완전히 같음(예: 전 leg가 oneway_shortest)
            seen_node_paths.append(node_path)

            slot_responses = [
                responses[min(slot, len(responses) - 1)] for responses, _ in leg_candidates
            ]
            diversity_candidates.append((
                PathUtils.path_score_vector(node_path, vector_lookup),
                self._stitch(slot_responses, total_legs),
            ))

        return PathUtils.select_diverse_paths(diversity_candidates, k=3)

    @staticmethod
    def _concat_leg_nodes(leg_node_paths: List[list]) -> list:
        """
        leg별 노드열을 하나로 이어붙인다. 인접 leg의 경계 노드는 같은 지점(stop)의
        동일 노드이므로, 두 번째 leg부터는 첫 노드를 건너뛴다(_stitch의 좌표 처리와 동일한 원리).
        """
        combined: list = []
        for i, nodes in enumerate(leg_node_paths):
            combined.extend(nodes[1:] if i > 0 else nodes)
        return combined

    def _stitch(self, leg_results: List[WalkRouteResponse], total_legs: int) -> WalkRouteResponse:
        """
        성공한 leg들의 좌표·거리를 이어 붙이고, 전체 상태를 판정합니다.
        - 모든 leg 성공: SUCCESS
        - 일부 leg만 성공: PARTIAL_ROUTE (성공한 구간까지만 반환)
        - 첫 leg부터 실패: 그 leg의 실패 status를 그대로 사용
        """
        successful = [r for r in leg_results if r.status == WalkRouteStatus.SUCCESS]

        coordinates: list = []
        total_m = 0.0
        for i, leg in enumerate(successful):
            # 인접 leg의 경계 좌표는 동일한 지점이므로 두 번째 leg부터 첫 좌표를 건너뜀
            coords = leg.coordinates[1:] if i > 0 else leg.coordinates
            coordinates.extend(coords)
            total_m += leg.total_km * 1000

        if len(successful) == total_legs:
            status = WalkRouteStatus.SUCCESS
        elif successful:
            status = WalkRouteStatus.PARTIAL_ROUTE
        else:
            status = leg_results[0].status

        total_km = round(total_m / 1000, 2)
        logger.info("경유지 경로 완성: status=%s, 성공 leg=%d/%d, total_km=%.2f",
                    status.value, len(successful), total_legs, total_km)

        return WalkRouteResponse(
            status      = status,
            mode        = self.mode,
            coordinates = coordinates,
            total_km    = total_km,
        )
