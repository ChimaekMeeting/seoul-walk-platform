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
from src.route_engine.scoring.detour_cap import apply_detour_cap
from src.route_engine.scoring.weighted_edge_cost import WeightedEdgeCost
from src.schema.route_schema import OnewayRouteInput, WaypointRouteInput, Weights

logger = logging.getLogger(__name__)

# leg_modes 값(WaypointRouteInput.WaypointLegMode)별로 재사용할 기존 편도 엔진
_LEG_ENGINES = {
    "oneway_shortest": OnewayAstarEngine,
    "oneway_random": OnewayBeamEngine,
    # 같은 A* 엔진에 안전·편안 가중 비용만 주입한 구간(#445). 엔진을 새로 만들지 않는다.
    "oneway_preferred": OnewayAstarEngine,
}

# 가중 비용을 적용하는 leg 방식. oneway_shortest는 사용자가 **명시적으로 고른** 최단
# 구간이므로 저장된 선호가 있어도 가중 연결로 바꾸지 않는다(#445 설계 결정 A).
_PREFERRED_LEG_MODE = "oneway_preferred"


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
        cost_context: Optional[WeightedEdgeCost] = None,
        preference_skipped_reason: Optional[str] = None,
        detour_max_ratio: float = 0.0,
    ):
        self.inp            = inp
        # 그래프를 직접 mutate하지 않고 leg 엔진에 그대로 넘기기만 하므로 복사가 필요 없다.
        # 실제 mutation(예: OnewayBeamEngine의 custom_score 계산)은 그걸 하는 leg 엔진이 자체적으로 격리한다.
        self.G               = G
        self.custom_weights  = custom_weights
        self.profile         = profile
        self.mode            = WalkMode.WAYPOINT
        # RouteService가 요청당 하나 만들어 넘긴다. 모든 leg가 같은 객체를 공유해야
        # 구간마다 다른 비용 기준으로 탐색하는 일이 없다.
        #
        # OnewayAstarEngine(oneway_shortest leg)에만 넘긴다. OnewayBeamEngine은 아직
        # scoring_engine.custom_score(할인 모델)로 탐색하는데, 두 모델은 방향이 반대라
        # 한 요청 안에서 섞으면 leg별 후보 비교가 불공정해진다(#445 설계 결정 A).
        self.cost_context    = cost_context
        # 가중 연결을 쓰지 못한 사유(RouteService가 판단해 넘긴다). 응답에 그대로 싣는다.
        self.preference_skipped_reason = preference_skipped_reason
        # 가중 경로가 거리 기준 대비 허용하는 실제 거리 증가 비율. 설정을 엔진이 직접
        # 읽지 않고 RouteService가 넘긴다 — 테스트가 monkeypatch 없이 값을 바꿀 수 있다.
        self.detour_max_ratio = detour_max_ratio
        # run()이 최종 선택을 끝낸 뒤에만 채워진다. 응답의 preference_applied는 "요청됐는가"가
        # 아니라 "최종 경로에 실제로 반영됐는가"여야 하므로 leg_modes가 아니라 이 값을 본다.
        self._applied: bool = False

    def _preference_requested(self) -> bool:
        """가중 연결을 쓰기로 하고 실제 leg에 반영됐는가(최종 선택 이전 단계)."""
        return self.cost_context is not None and _PREFERRED_LEG_MODE in self.inp.leg_modes

    def _leg_cost_kwargs(self, mode: str) -> dict:
        """leg 엔진에 넘길 비용 인자. oneway_preferred 구간에만 가중 비용을 넘긴다."""
        if self.cost_context is None or mode != _PREFERRED_LEG_MODE:
            return {}
        return {"cost_context": self.cost_context}

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
                **self._leg_cost_kwargs(mode),
            )
            leg_responses = engine.run()  # oneway_random이면 최대 3개, oneway_shortest면 1개
            leg_node_paths = engine.last_path_nodes_by_candidate
            result = leg_responses[0]  # 대표 후보 — 상태 판정·재시도 로직은 기존처럼 이걸 기준으로 한다

            # 다른 엔진들의 base_shortest 대체와 같은 패턴: 실패하면 최단 경로로 재시도
            if result.status != WalkRouteStatus.SUCCESS and mode != "oneway_shortest":
                logger.warning("leg %d(%s)에서 실패해 최단 경로로 대체합니다: status=%s",
                               i + 1, mode, result.status.value)
                # 대체는 순수 거리 기준이다 — 가중치도 재방문 페널티도 걸지 않는다.
                # 앞선 시도가 이미 실패했으므로 추가 제약을 남겨 두면 대체까지 같은
                # 이유로 실패할 수 있다(#445).
                engine = OnewayAstarEngine(
                    leg_inp, self.G, custom_weights=self.custom_weights, profile=self.profile,
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
            if self._preference_requested():
                # 일부 구간이 빠진 경로에는 우회 상한을 적용할 수 없다(비교할 전체
                # 기준 경로가 없다). 선호가 반영됐다고 보고하지 않고 사유를 남긴다.
                self._applied = False
                self.preference_skipped_reason = "partial_route"
            leg_results = [responses[0] for responses, _ in leg_candidates]
            return [self._stitch(leg_results, total_legs)]

        # 가중 연결을 썼다면 완성된 경로 전체에 우회 상한을 적용한다. leg마다가 아니라
        # 여기서 한 번 하는 이유는 상한이 요청 전체의 성질이기 때문이다 — leg마다
        # 독립 적용하면 5구간 경로가 허용치를 leg 수만큼 넘길 수 있다.
        if self._preference_requested():
            leg_candidates = self._apply_detour_cap(stops, leg_candidates)

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

    def _build_distance_baseline(self, stops: List[tuple]) -> Optional[List[tuple]]:
        """같은 스냅 노드·경유지 순서로 거리 기준 경로를 다시 만든다. 실패하면 None.

        가중치도 재방문 페널티도 걸지 않는다 — 우회 상한의 기준선은 순수 물리 최단이어야
        한다. leg마다 A*를 한 번씩 더 호출하므로 가중 요청의 A* 호출 수가 두 배가 된다.

        같은 leg_inp(좌표)를 쓰므로 OnewayAstarEngine.find_nearest_node가 같은 노드로
        스냅한다 — 두 경로가 같은 출발·도착·경유지를 지난다는 보장이 여기서 나온다.
        """
        baseline: List[tuple] = []
        for i in range(len(self.inp.leg_modes)):
            start_lat, start_lon = stops[i]
            end_lat, end_lon     = stops[i + 1]
            engine = OnewayAstarEngine(
                OnewayRouteInput(
                    start_lat=start_lat, start_lon=start_lon,
                    end_lat=end_lat, end_lon=end_lon,
                    target_km=self.inp.leg_target_km[i],
                ),
                self.G, custom_weights=self.custom_weights, profile=self.profile,
            )
            responses = engine.run()
            if responses[0].status != WalkRouteStatus.SUCCESS:
                logger.warning("우회 상한 기준 경로 생성에 실패했습니다: leg=%d status=%s",
                               i + 1, responses[0].status.value)
                return None
            baseline.append((responses, engine.last_path_nodes_by_candidate))
        return baseline

    def _apply_detour_cap(self, stops: List[tuple], leg_candidates: List[tuple]) -> List[tuple]:
        """가중 경로가 상한을 넘으면 거리 기준 경로로 통째로 되돌린다.

        반올림 전 거리(length 합)로 비교한다 — leg별 total_km는 이미 소수점 둘째 자리에서
        반올림돼 leg마다 최대 5m씩 오차가 쌓인다.
        """
        preferred_nodes = self._concat_leg_nodes([
            node_paths[0] for _, node_paths in leg_candidates
        ])
        baseline = self._build_distance_baseline(stops)
        baseline_nodes = self._concat_leg_nodes(
            [node_paths[0] for _, node_paths in baseline]
        ) if baseline is not None else None

        decision = apply_detour_cap(
            self.G, preferred_nodes, baseline_nodes, self.detour_max_ratio,
        )

        if not decision.verified:
            # 기준 경로를 못 만들었다. 가중 경로는 그대로 쓰되 검증했다고 표시하지 않는다.
            self._applied = True
            self.preference_skipped_reason = "baseline_failed"
            return leg_candidates

        if decision.capped:
            logger.info(
                "우회 상한을 넘어 거리 기준 경로로 되돌립니다: %.1fm -> %.1fm (우회율 %.3f > %.3f)",
                decision.physical_distance_m, decision.weighted_distance_m,
                decision.detour_ratio, self.detour_max_ratio,
            )
            self._applied = False
            self.preference_skipped_reason = "detour_cap_exceeded"
            return baseline

        self._applied = True
        self.preference_skipped_reason = None
        return leg_candidates

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
            preference_applied        = self._applied,
            preference_skipped_reason = self.preference_skipped_reason,
        )
