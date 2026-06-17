import networkx as nx

from src.schema.route_schema import (
    CircularMode, CircularRouteInput, FallbackReason,
    OnewayMode, OnewayRouteInput, RouteOutput,
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


class RouteService:
    def __init__(self, G: nx.Graph):
        self.G = G
        
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
        context: dict
    ) -> RouteOutput:
        """
        context에 적합한 경로 생성 엔진을 호출합니다.
        """
        mode        = context.get("mode", "circular_random")
        start_lat   = context["origin"]["coordinate"]["lat"]
        start_lon   = context["origin"]["coordinate"]["lon"]
        distance_km = context.get("distance_km", 3.0)

        # 매핑 가능한 모드가 없는 경우
        if mode not in self._circular_engines and mode not in self._oneway_engines:
            return RouteOutput(status="FAILED", mode=mode, coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.UNKNOWN_ERROR)

        # 엔진 생성
        try:
            engine = self._build_engine(mode, self.G, start_lat, start_lon, distance_km, context)
        except ValueError:
            return RouteOutput(status="FAILED", mode=mode, coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.INVALID_DESTINATION)

        # 3. 경로 생성
        return engine.run()
    
    def _build_engine(
        self,
        mode: str,
        start_lat: float,
        start_lon: float,
        distance_km: float,
        context: dict,
    ):
        """
        경로 생성 엔진을 호출합니다.
        """
        # 1. 순환 모드인 경우
        if mode in self._circular_engines:
            inp        = CircularRouteInput(start_lat=start_lat, start_lon=start_lon, target_km=distance_km)
            engine_cls = self._circular_engines[mode]
            return engine_cls(inp, self.G)
        
        # 2. 편도 모드인 경우
        dest = context.get("destination")

        # 목적지가 없는 경우
        if dest is None:
            raise ValueError(f"{mode} 모드에서는 destination이 필요합니다")
        
        inp = OnewayRouteInput(
            start_lat=start_lat, start_lon=start_lon,
            end_lat=dest["coordinate"]["lat"],
            end_lon=dest["coordinate"]["lon"],
            target_km=distance_km,
        )
        engine_cls = self._oneway_engines[mode]
        return engine_cls(inp, self.G)
