import logging
import networkx as nx
from typing import Optional, Union

from src.interfaces.schema.walk_schema import (
    WalkRouteResponse,
    WalkRouteStatus,
    CircularMode,
    OnewayMode,
    Coordinate,
)
from src.schema.route_schema import (
    OnewayRouteInput,
    CircularRouteInput
)
from src.route_engine.engines import (
    CircularChildEngine,
    CircularRandomEngine,
    CircularRunningEngine,
    OnewayChildEngine,
    OnewayDijkstraEngine,
    OnewayRandomEngine,
    OnewayRunningEngine,
)
from src.route_engine.engines.path_utils import PathUtils
from src.service.user.auth_service import AuthService
from src.interfaces.schema.auth_schema import Status

logger = logging.getLogger(__name__)


class RouteService:
    def __init__(self, G: nx.Graph, auth_service: AuthService):
        self.G = G
        self.auth_service = auth_service
        
        self._circular_engines: dict = {
            CircularMode.RANDOM:  CircularRandomEngine,
            CircularMode.CHILD:   CircularChildEngine,
            CircularMode.RUNNING: CircularRunningEngine,
        }
        self._oneway_engines: dict = {
            OnewayMode.SHORTEST: OnewayDijkstraEngine,
            OnewayMode.RANDOM:   OnewayRandomEngine,
            OnewayMode.CHILD:    OnewayChildEngine,
            OnewayMode.RUNNING:  OnewayRunningEngine,
        }

    def get_route(
        self,
        access_token: str,
        origin: Coordinate,
        destination: Optional[Coordinate] = None,
        target_km: Optional[float] = None,
        mode: Union[CircularMode, OnewayMode] = CircularMode.RANDOM
    ) -> WalkRouteResponse:
        """
        context에 적합한 경로 생성 엔진을 호출합니다.
        """
        logger.info(
            "walk route request: mode=%s origin=(%.5f, %.5f) has_destination=%s target_km=%s",
            mode, origin.lat, origin.lon, destination is not None, target_km,
        )

        # 사용자 인증
        auth_status, *_ = self.auth_service.check_access_token(access_token)
        if auth_status != Status.SUCCESS:
            logger.warning("walk route auth failed: mode=%s status=%s", mode, auth_status.value)
            return WalkRouteResponse(status=WalkRouteStatus(auth_status.value), mode=mode, coordinates=[], total_km=0.0)

        # 매핑 가능한 모드가 없는 경우
        if mode not in self._circular_engines and mode not in self._oneway_engines:
            logger.warning("walk route unknown mode: mode=%s", mode)
            return WalkRouteResponse(status=WalkRouteStatus.UNKNOWN_ERROR, mode=mode, coordinates=[], total_km=0.0)

        # ROUT-NODE-001/002: 엔진 호출 전 보행 노드 존재 여부 선행 검증
        utils = PathUtils(self.G)
        if utils.find_nearest_node_with_expansion(origin.lat, origin.lon) is None:
            logger.warning("walk route no nearest start node: mode=%s", mode)
            return WalkRouteResponse(status=WalkRouteStatus.NO_NEAREST_START_NODE, mode=mode, coordinates=[], total_km=0.0)
        if isinstance(mode, OnewayMode) and destination is not None:
            if utils.find_nearest_node_with_expansion(destination.lat, destination.lon) is None:
                logger.warning("walk route no nearest end node: mode=%s", mode)
                return WalkRouteResponse(status=WalkRouteStatus.NO_NEAREST_END_NODE, mode=mode, coordinates=[], total_km=0.0)

        # 엔진 생성
        try:
            engine = self._build_engine(mode, origin, destination, target_km)
        except ValueError:
            logger.warning("walk route invalid destination: mode=%s", mode)
            return WalkRouteResponse(status=WalkRouteStatus.INVALID_DESTINATION, mode=mode, coordinates=[], total_km=0.0)

        logger.info("walk route engine selected: mode=%s engine=%s", mode, type(engine).__name__)

        # 3. 경로 생성
        result = engine.run()
        logger.info("walk route result: mode=%s status=%s total_km=%s", mode, result.status.value, result.total_km)
        return result
    
    def _build_engine(
        self,
        mode: Union[CircularMode, OnewayMode],
        origin: Coordinate,
        destination: Optional[Coordinate] = None,
        target_km: Optional[float] = None
    ):
        """
        경로 생성 엔진을 호출합니다.
        """
        # 1. 순환 모드인 경우
        if mode in self._circular_engines:
            inp = CircularRouteInput(
                start_lat=origin.lat,
                start_lon=origin.lon,
                target_km=target_km
            )
            engine_cls = self._circular_engines[mode]
            return engine_cls(inp, self.G)
        
        # 2. 편도 모드인 경우

        # 목적지가 없는 경우
        if destination is None:
            raise ValueError(f"{mode} 모드에서는 destination이 필요합니다")
        
        inp = OnewayRouteInput(
            start_lat=origin.lat,
            start_lon=origin.lon,
            end_lat=destination.lat,
            end_lon=destination.lon,
            target_km=target_km,
        )
        engine_cls = self._oneway_engines[mode]
        return engine_cls(inp, self.G)
