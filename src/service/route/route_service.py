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
from src.service.user.auth_service import AuthService
from src.repository.user.user_repository import UserRepository
from src.interfaces.schema.auth_schema import Status


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
        # 사용자 인증
        # status, provider, provider_id = self.auth_service.check_access_token(access_token)
        # if status != Status.SUCCESS:
        #     return WalkRouteResponse(status="FAILED", mode=mode, coordinates=[], total_km=0.0,
        #                             fallback_reason=status)
        
        # 추후 사용자에게 추천한 경로를 저장하기 위해 필요
        # user = UserRepository.find_by_provider_and_provider_id(provider, provider_id)

        # 매핑 가능한 모드가 없는 경우
        if mode not in self._circular_engines and mode not in self._oneway_engines:
            return WalkRouteResponse(status="FAILED", mode=mode, coordinates=[], total_km=0.0,
                                    fallback_reason=FallbackReason.UNKNOWN_ERROR)

        # 엔진 생성
        try:
            engine = self._build_engine(mode, origin, destination, target_km)
        except ValueError:
            return WalkRouteResponse(status="FAILED", mode=mode, coordinates=[], total_km=0.0,
                                    fallback_reason=FallbackReason.INVALID_DESTINATION)

        # 3. 경로 생성
        return engine.run()
    
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
