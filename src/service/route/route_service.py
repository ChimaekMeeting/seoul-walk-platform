import logging
from typing import Optional, List

import networkx as nx

from src.interfaces.schema.auth_schema import Status
from src.interfaces.schema.walk_schema import (
    Coordinate,
    RoutePoiItem,
    WalkMode,
    WalkRouteResponse,
    WalkRouteStatus,
)
from src.repository.user.route_history_repository import RouteHistoryRepository
from src.repository.user.user_repository import UserRepository
from src.repository.layer.route_poi_repository import RoutePoiRepository
from src.route_engine.engines import (
    CircularBeamEngine,
    GpsArtEngine,
    OnewayAstarEngine,
    OnewayBeamEngine,
    WaypointComposerEngine,
)
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.profiles import ScoringProfile
from src.schema.route_schema import (
    CircularRouteInput,
    GpsArtPoint,
    GpsArtRouteInput,
    OnewayRouteInput,
    WaypointCoordinate,
    WaypointLegMode,
    WaypointRouteInput,
    Weights,
)
from src.service.user.auth_service import AuthService

logger = logging.getLogger(__name__)


class RouteService:
    def __init__(self, G: nx.Graph, auth_service: AuthService):
        self.G = G
        self.auth_service = auth_service

        self.base_engines: dict = {
            WalkMode.CIRCULAR_RANDOM: CircularBeamEngine,
            WalkMode.ONEWAY_SHORTEST: OnewayAstarEngine,
            WalkMode.ONEWAY_RANDOM: OnewayBeamEngine,
            WalkMode.GPS_ART: GpsArtEngine,
            WalkMode.WAYPOINT: WaypointComposerEngine,
        }

    def get_route(
        self,
        access_token: str,
        origin: Coordinate,
        destination: Optional[Coordinate] = None,
        target_km: Optional[float] = None,
        mode: WalkMode = WalkMode.CIRCULAR_RANDOM,
        custom_weights: Optional[Weights] = None,
        profile: Optional[ScoringProfile] = None,
        shape_points: Optional[List[GpsArtPoint]] = None,
        waypoints: Optional[List[Coordinate]] = None,
        leg_modes: Optional[List[WaypointLegMode]] = None,
        leg_target_km: Optional[List[Optional[float]]] = None,
    ) -> List[WalkRouteResponse]:
        """
        context에 적합한 경로 생성 엔진을 호출합니다.
        mode는 경로 생성 방식(circular_random/oneway_shortest/oneway_random/gps_art/waypoint)을,
        profile은 어떤 score 조합을 선호할지(scoring profile)를 결정하며 서로 독립적입니다.
        custom_weights가 있으면 profile.weights를 base로 두고 해당 필드만 override합니다.
        shape_points는 gps_art 모드 전용이며, 호출 전에 이미 도형 이름 -> 좌표 변환이
        끝난 상태여야 합니다(RouteService는 이미지 생성 등 비동기 작업을 하지 않음).
        waypoints/leg_modes/leg_target_km은 waypoint 모드 전용이다. leg_modes[i]/leg_target_km[i]는
        origin -> waypoints[0] -> ... -> destination 순서상 i번째 구간의 이동 방식이며,
        지정하지 않은 구간은 최단 경로(oneway_shortest)로 채워진다.
        """
        logger.info(
            "walk route request: mode=%s origin=(%.5f, %.5f) has_destination=%s target_km=%s",
            mode,
            origin.lat,
            origin.lon,
            destination is not None,
            target_km,
        )

        auth_status, provider, provider_id = self.auth_service.check_access_token(access_token)
        if auth_status != Status.SUCCESS:
            logger.warning("walk route auth failed: mode=%s status=%s", mode, auth_status.value)
            return [WalkRouteResponse(
                status=WalkRouteStatus(auth_status.value),
                mode=mode,
                coordinates=[],
                total_km=0.0,
            )]

        if mode not in self.base_engines:
            logger.warning("walk route unknown mode: mode=%s", mode)
            return [WalkRouteResponse(
                status=WalkRouteStatus.UNKNOWN_ERROR,
                mode=mode,
                coordinates=[],
                total_km=0.0,
            )]

        utils = PathUtils(self.G)
        if utils.find_nearest_node_with_expansion(origin.lat, origin.lon) is None:
            logger.warning("walk route no nearest start node: mode=%s", mode)
            return [WalkRouteResponse(
                status=WalkRouteStatus.NO_NEAREST_START_NODE,
                mode=mode,
                coordinates=[],
                total_km=0.0,
            )]

        if mode != WalkMode.CIRCULAR_RANDOM and destination is not None:
            if utils.find_nearest_node_with_expansion(destination.lat, destination.lon) is None:
                logger.warning("walk route no nearest end node: mode=%s", mode)
                return [WalkRouteResponse(
                    status=WalkRouteStatus.NO_NEAREST_END_NODE,
                    mode=mode,
                    coordinates=[],
                    total_km=0.0,
                )]

        if mode == WalkMode.WAYPOINT and waypoints:
            for wp in waypoints:
                if utils.find_nearest_node_with_expansion(wp.lat, wp.lon) is None:
                    logger.warning("walk route no nearest waypoint node: mode=%s", mode)
                    return [WalkRouteResponse(
                        status=WalkRouteStatus.NO_NEAREST_END_NODE,
                        mode=mode,
                        coordinates=[],
                        total_km=0.0,
                    )]

        try:
            engine = self._build_engine(
                mode, origin, destination, target_km, custom_weights, profile, shape_points,
                waypoints, leg_modes, leg_target_km,
            )
        except ValueError:
            logger.warning("walk route invalid destination: mode=%s", mode)
            return [WalkRouteResponse(
                status=WalkRouteStatus.INVALID_DESTINATION,
                mode=mode,
                coordinates=[],
                total_km=0.0,
            )]

        logger.info("walk route engine selected: mode=%s engine=%s", mode, type(engine).__name__)

        results = engine.run()
        # circular_random/oneway_random은 이제 최대 3개까지 다양화한 후보를 반환한다(results[0]이 대표 후보).
        # POI는 성공한 후보 전부에 붙이고, RouteHistory는 아직 대표 후보 1개만 저장한다
        # — 사용자가 실제로 어떤 후보를 골랐는지는 아직 API로 전달받지 않기 때문이다.
        # TODO: 사용자가 후보 중 하나를 선택하는 흐름이 생기면, 그때 선택된 후보를 저장하도록 바꾼다.
        first_result = results[0]
        logger.info(
            "walk route result: mode=%s status=%s total_km=%s candidates=%d",
            mode, first_result.status.value, first_result.total_km, len(results),
        )

        for result in results:
            if result.status != WalkRouteStatus.SUCCESS:
                continue
            try:
                result.nearby_pois = [
                    RoutePoiItem.model_validate(poi)
                    for poi in RoutePoiRepository.find_near_route(
                        result.coordinates
                    )
                ]
            except Exception:
                logger.exception("route POI lookup failed: mode=%s", mode)

        if first_result.status == WalkRouteStatus.SUCCESS:
            try:
                user = UserRepository.find_by_provider_and_provider_id(provider, provider_id)
                if user is not None:
                    history = RouteHistoryRepository.save(
                        user_id=user.id,
                        mode=mode,
                        origin_lat=origin.lat,
                        origin_lon=origin.lon,
                        coordinates=first_result.coordinates,
                        total_km=first_result.total_km,
                        destination_lat=destination.lat if destination else None,
                        destination_lon=destination.lon if destination else None,
                    )
                    first_result.id = history.id
            except Exception:
                logger.exception("walk route history save failed: mode=%s", mode)

        return results

    def _build_engine(
        self,
        mode: WalkMode,
        origin: Coordinate,
        destination: Optional[Coordinate] = None,
        target_km: Optional[float] = None,
        custom_weights: Optional[Weights] = None,
        profile: Optional[ScoringProfile] = None,
        shape_points: Optional[List[GpsArtPoint]] = None,
        waypoints: Optional[List[Coordinate]] = None,
        leg_modes: Optional[List[WaypointLegMode]] = None,
        leg_target_km: Optional[List[Optional[float]]] = None,
    ):
        """profile/custom_weights를 엔진에 주입해 경로 생성 엔진 인스턴스를 반환합니다."""
        if mode == WalkMode.CIRCULAR_RANDOM:
            inp = CircularRouteInput(
                start_lat=origin.lat,
                start_lon=origin.lon,
                target_km=target_km,
            )
            return self.base_engines[mode](inp, self.G, custom_weights=custom_weights, profile=profile)

        if mode == WalkMode.GPS_ART:
            if not shape_points:
                raise ValueError(f"{mode} 모드에서는 shape_points가 필요합니다")
            if target_km is None:
                raise ValueError(f"{mode} 모드에서는 target_km이 필요합니다")
            inp = GpsArtRouteInput(
                shape_points=shape_points,
                origin_lat=origin.lat,
                origin_lon=origin.lon,
                target_km=target_km,
            )
            # GpsArtEngine은 내부적으로 leg마다 oneway_shortest만 써서 custom_weights/profile을 받지 않음
            return self.base_engines[mode](inp, self.G)

        if mode == WalkMode.WAYPOINT:
            if destination is None:
                raise ValueError(f"{mode} 모드에서는 destination이 필요합니다")

            stop_waypoints = waypoints or []
            expected_legs  = len(stop_waypoints) + 1

            # 지정하지 않은 구간은 최단 경로(oneway_shortest)로 채운다.
            padded_modes = list(leg_modes or [])
            padded_modes += ["oneway_shortest"] * (expected_legs - len(padded_modes))
            padded_target_km = list(leg_target_km or [])
            padded_target_km += [None] * (expected_legs - len(padded_target_km))

            inp = WaypointRouteInput(
                start_lat=origin.lat,
                start_lon=origin.lon,
                end_lat=destination.lat,
                end_lon=destination.lon,
                waypoints=[WaypointCoordinate(lat=wp.lat, lon=wp.lon) for wp in stop_waypoints],
                leg_modes=padded_modes,
                leg_target_km=padded_target_km,
            )
            return self.base_engines[mode](inp, self.G, custom_weights=custom_weights, profile=profile)

        if destination is None:
            raise ValueError(f"{mode} 모드에서는 destination이 필요합니다")

        inp = OnewayRouteInput(
            start_lat=origin.lat,
            start_lon=origin.lon,
            end_lat=destination.lat,
            end_lon=destination.lon,
            target_km=target_km,
        )
        return self.base_engines[mode](inp, self.G, custom_weights=custom_weights, profile=profile)
