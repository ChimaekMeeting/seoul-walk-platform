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
from src.route_engine.profiles import ScoringProfile
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
    """

    def __init__(
        self,
        inp: WaypointRouteInput,
        G: nx.Graph,
        custom_weights: Optional[Weights] = None,
        profile: Optional[ScoringProfile] = None,
    ):
        self.inp            = inp
        self.G               = G.copy()  # 모든 leg가 공유하는 원본 보호용 복사본 1개
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

        leg_results: List[WalkRouteResponse] = []
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
            )
            result = engine.run()[0]  # leg 엔진도 후보 리스트를 반환하므로 1개만 사용

            # 다른 엔진들의 base_shortest 대체와 같은 패턴: 실패하면 최단 경로로 재시도
            if result.status != WalkRouteStatus.SUCCESS and mode != "oneway_shortest":
                logger.warning("leg %d(%s)에서 실패해 최단 경로로 대체합니다: status=%s",
                               i + 1, mode, result.status.value)
                fallback = OnewayAstarEngine(
                    leg_inp, self.G, custom_weights=self.custom_weights, profile=self.profile,
                )
                result = fallback.run()[0]

            leg_results.append(result)

            logger.info("leg %d/%d 결과: mode=%s status=%s", i + 1, len(self.inp.leg_modes), mode, result.status.value)

            if result.status != WalkRouteStatus.SUCCESS:
                logger.warning("leg %d에서 최단 경로 대체도 실패해 이후 leg를 생략합니다: status=%s", i + 1, result.status.value)
                break

        return [self._stitch(leg_results, len(self.inp.leg_modes))]

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
