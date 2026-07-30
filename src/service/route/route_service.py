import logging
from typing import Optional

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
    OnewayDijkstraEngine,
    OnewayBeamEngine,
)
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.profiles import ScoringProfile
from src.schema.route_schema import CircularRouteInput, OnewayRouteInput, Weights
from src.service.user.auth_service import AuthService

logger = logging.getLogger(__name__)


class RouteService:
    def __init__(self, G: nx.Graph, auth_service: AuthService):
        self.G = G
        self.auth_service = auth_service

        self.base_engines: dict = {
            WalkMode.CIRCULAR_RANDOM: CircularBeamEngine,
            WalkMode.ONEWAY_SHORTEST: OnewayDijkstraEngine,
            WalkMode.ONEWAY_RANDOM: OnewayBeamEngine,
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
    ) -> WalkRouteResponse:
        """
        context에 적합한 경로 생성 엔진을 호출합니다.
        mode는 경로 생성 방식(circular_random/oneway_shortest/oneway_random)을,
        profile은 어떤 score 조합을 선호할지(scoring profile)를 결정하며 서로 독립적입니다.
        custom_weights가 있으면 profile.weights를 base로 두고 해당 필드만 override합니다.
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
            return WalkRouteResponse(
                status=WalkRouteStatus(auth_status.value),
                mode=mode,
                coordinates=[],
                total_km=0.0,
            )

        if mode not in self.base_engines:
            logger.warning("walk route unknown mode: mode=%s", mode)
            return WalkRouteResponse(
                status=WalkRouteStatus.UNKNOWN_ERROR,
                mode=mode,
                coordinates=[],
                total_km=0.0,
            )

        utils = PathUtils(self.G)
        if utils.find_nearest_node_with_expansion(origin.lat, origin.lon) is None:
            logger.warning("walk route no nearest start node: mode=%s", mode)
            return WalkRouteResponse(
                status=WalkRouteStatus.NO_NEAREST_START_NODE,
                mode=mode,
                coordinates=[],
                total_km=0.0,
            )

        if mode != WalkMode.CIRCULAR_RANDOM and destination is not None:
            if utils.find_nearest_node_with_expansion(destination.lat, destination.lon) is None:
                logger.warning("walk route no nearest end node: mode=%s", mode)
                return WalkRouteResponse(
                    status=WalkRouteStatus.NO_NEAREST_END_NODE,
                    mode=mode,
                    coordinates=[],
                    total_km=0.0,
                )

        try:
            engine = self._build_engine(mode, origin, destination, target_km, custom_weights, profile)
        except ValueError:
            logger.warning("walk route invalid destination: mode=%s", mode)
            return WalkRouteResponse(
                status=WalkRouteStatus.INVALID_DESTINATION,
                mode=mode,
                coordinates=[],
                total_km=0.0,
            )

        logger.info("walk route engine selected: mode=%s engine=%s", mode, type(engine).__name__)

        result = engine.run()
        logger.info("walk route result: mode=%s status=%s total_km=%s", mode, result.status.value, result.total_km)

        if result.status == WalkRouteStatus.SUCCESS:
            try:
                result.nearby_pois = [
                    RoutePoiItem.model_validate(poi)
                    for poi in RoutePoiRepository.find_near_route(
                        result.coordinates
                    )
                ]
            except Exception:
                logger.exception("route POI lookup failed: mode=%s", mode)

            try:
                user = UserRepository.find_by_provider_and_provider_id(provider, provider_id)
                if user is not None:
                    history = RouteHistoryRepository.save(
                        user_id=user.id,
                        mode=mode,
                        origin_lat=origin.lat,
                        origin_lon=origin.lon,
                        coordinates=result.coordinates,
                        total_km=result.total_km,
                        destination_lat=destination.lat if destination else None,
                        destination_lon=destination.lon if destination else None,
                    )
                    result.id = history.id
            except Exception:
                logger.exception("walk route history save failed: mode=%s", mode)

        return result

    def _build_engine(
        self,
        mode: WalkMode,
        origin: Coordinate,
        destination: Optional[Coordinate] = None,
        target_km: Optional[float] = None,
        custom_weights: Optional[Weights] = None,
        profile: Optional[ScoringProfile] = None,
    ):
        """profile/custom_weights를 엔진에 주입해 경로 생성 엔진 인스턴스를 반환합니다."""
        if mode == WalkMode.CIRCULAR_RANDOM:
            inp = CircularRouteInput(
                start_lat=origin.lat,
                start_lon=origin.lon,
                target_km=target_km,
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
