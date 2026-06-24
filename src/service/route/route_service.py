import networkx as nx
from typing import Optional

from src.interfaces.schema.walk_schema import (
    WalkRouteResponse,
    WalkMode,
    Coordinate,
    FallbackReason
)
from src.schema.route_schema import (
    OnewayRouteInput,
    CircularRouteInput,
    Weights,
)
from src.route_engine.engines import (
    CircularRandomEngine,
    OnewayDijkstraEngine,
    OnewayRandomEngine,
)
from src.route_engine.engines.path_utils import PathUtils
from src.service.user.auth_service import AuthService
from src.repository.user.user_repository import UserRepository
from src.repository.user.route_history_repository import RouteHistoryRepository
from src.interfaces.schema.auth_schema import Status


class RouteService:
    def __init__(self, G: nx.Graph, auth_service: AuthService):
        self.G = G
        self.auth_service = auth_service

        self.base_engines: dict = {
            WalkMode.CIRCULAR_RANDOM: CircularRandomEngine,
            WalkMode.ONEWAY_SHORTEST: OnewayDijkstraEngine,
            WalkMode.ONEWAY_RANDOM:   OnewayRandomEngine,
        }

    def get_route(
        self,
        access_token: str,
        origin: Coordinate,
        destination: Optional[Coordinate] = None,
        target_km: Optional[float] = None,
        mode: WalkMode = WalkMode.CIRCULAR_RANDOM,
        custom_weights: Optional[Weights] = None,
    ) -> WalkRouteResponse:
        """
        context에 적합한 경로 생성 엔진을 호출합니다.
        custom_weights가 있으면 모드 프로필 대신 해당 가중치를 사용합니다.
        """
        # 사용자 인증
        status, provider, provider_id = self.auth_service.check_access_token(access_token)
        if status != Status.SUCCESS:
            return WalkRouteResponse(
                status="FAILED",
                mode=mode,
                coordinates=[],
                total_km=0.0,
                fallback_reason=status
            )

        # 추후 사용자에게 추천한 경로를 저장하기 위해 필요
        user = UserRepository.find_by_provider_and_provider_id(provider, provider_id)

        # 매핑 가능한 모드가 없는 경우
        if mode not in self.base_engines:
            return WalkRouteResponse(
                status="FAILED",
                mode=mode,
                coordinates=[],
                total_km=0.0,
                fallback_reason=FallbackReason.UNKNOWN_ERROR
            )

        # ROUT-NODE-001/002: 엔진 호출 전 보행 노드 존재 여부 선행 검증
        utils = PathUtils(self.G)
        if utils.find_nearest_node_with_expansion(origin.lat, origin.lon) is None:
            raise ValueError("출발지 주변에서 연결 가능한 보행 도로를 찾을 수 없습니다.")
        if mode != WalkMode.CIRCULAR_RANDOM and destination is not None:
            if utils.find_nearest_node_with_expansion(destination.lat, destination.lon) is None:
                raise ValueError("목적지 주변에서 연결 가능한 보행 도로를 찾을 수 없습니다.")

        # 엔진 생성
        try:
            engine = self._build_engine(mode, origin, destination, target_km, custom_weights)
        except ValueError:
            return WalkRouteResponse(
                status="FAILED",
                mode=mode,
                coordinates=[],
                total_km=0.0,
                fallback_reason=FallbackReason.INVALID_DESTINATION
            )

        # 경로 생성
        result = engine.run()

        # 성공 시 추천 경로 기록 저장
        if result.status == "SUCCESS" and user is not None:
            RouteHistoryRepository.save(
                user_id=user.id,
                mode=mode,
                origin_lat=origin.lat,
                origin_lon=origin.lon,
                coordinates=result.coordinates,
                total_km=result.total_km,
                destination_lat=destination.lat if destination else None,
                destination_lon=destination.lon if destination else None,
            )

        return result

    def _build_engine(
        self,
        mode: WalkMode,
        origin: Coordinate,
        destination: Optional[Coordinate] = None,
        target_km: Optional[float] = None,
        custom_weights: Optional[Weights] = None,
    ):
        """
        custom_weights를 엔진에 주입해 경로 생성 엔진 인스턴스를 반환합니다.
        """
        # 1. 순환 모드
        if mode == WalkMode.CIRCULAR_RANDOM:
            inp = CircularRouteInput(
                start_lat=origin.lat,
                start_lon=origin.lon,
                target_km=target_km,
            )
            return self.base_engines[mode](inp, self.G, custom_weights=custom_weights)

        # 2. 편도 모드 (목적지 필수)
        if destination is None:
            raise ValueError(f"{mode} 모드에서는 destination이 필요합니다")

        inp = OnewayRouteInput(
            start_lat=origin.lat,
            start_lon=origin.lon,
            end_lat=destination.lat,
            end_lon=destination.lon,
            target_km=target_km,
        )
        return self.base_engines[mode](inp, self.G, custom_weights=custom_weights)
