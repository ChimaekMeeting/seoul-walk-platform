import networkx as nx
from typing import Optional, Union

from src.interfaces.schema.walk_schema import (
    WalkRouteResponse,
    CircularMode,
    OnewayMode,
    Coordinate,
    FallbackReason
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
from src.repository.user.user_repository import UserRepository
from src.interfaces.schema.auth_schema import Status
from src.schema.route_schema import OnewayRouteInput, CircularRouteInput, Weights


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
        mode: Union[CircularMode, OnewayMode] = CircularMode.RANDOM,
        custom_weights: Optional[Weights] = None,
    ) -> WalkRouteResponse:
        """
        context에 적합한 경로 생성 엔진을 호출합니다.
        custom_weights가 있으면 모드 프로필 대신 해당 가중치를 사용합니다.
        """
        # 사용자 인증
        status, *_ = self.auth_service.check_access_token(access_token)
        if status != Status.SUCCESS:
            return WalkRouteResponse(status="FAILED", mode=mode, coordinates=[], total_km=0.0,
                                    fallback_reason=status)

        # 매핑 가능한 모드가 없는 경우
        if mode not in self._circular_engines and mode not in self._oneway_engines:
            return WalkRouteResponse(status="FAILED", mode=mode, coordinates=[], total_km=0.0,
                                    fallback_reason=FallbackReason.UNKNOWN_ERROR)

        # ROUT-NODE-001/002: 엔진 호출 전 보행 노드 존재 여부 선행 검증
        utils = PathUtils(self.G)
        if utils.find_nearest_node_with_expansion(origin.lat, origin.lon) is None:
            raise ValueError("출발지 주변에서 연결 가능한 보행 도로를 찾을 수 없습니다.")
        if isinstance(mode, OnewayMode) and destination is not None:
            if utils.find_nearest_node_with_expansion(destination.lat, destination.lon) is None:
                raise ValueError("목적지 주변에서 연결 가능한 보행 도로를 찾을 수 없습니다.")

        # 엔진 생성
        try:
            engine = self._build_engine(mode, origin, destination, target_km, custom_weights)
        except ValueError:
            return WalkRouteResponse(status="FAILED", mode=mode, coordinates=[], total_km=0.0,
                                    fallback_reason=FallbackReason.INVALID_DESTINATION)

        # 3. 경로 생성
        return engine.run()
    
    def _build_engine(self, mode, origin, destination=None, target_km=None, custom_weights=None):
        """custom_weights를 엔진에 주입해 경로 생성 엔진 인스턴스를 반환합니다."""
        if mode in self._circular_engines:
            inp = CircularRouteInput(start_lat=origin.lat, start_lon=origin.lon, target_km=target_km)
            return self._circular_engines[mode](inp, self.G, custom_weights=custom_weights)
        if destination is None:
            raise ValueError(f"{mode} 모드에서는 destination이 필요합니다")
        inp = OnewayRouteInput(start_lat=origin.lat, start_lon=origin.lon, end_lat=destination.lat, end_lon=destination.lon, target_km=target_km)
        return self._oneway_engines[mode](inp, self.G, custom_weights=custom_weights)
