import asyncio
from langchain_core.tools import StructuredTool

from src.service.route.route_service import RouteService

route_service = RouteService()


def _circular_context(start_lat: float, start_lon: float, distance_km: float, mode: str) -> dict:
    return {
        "mode":        mode,
        "distance_km": distance_km,
        "origin":      {"coordinate": {"lat": start_lat, "lon": start_lon}},
    }


def _oneway_context(
    start_lat: float, start_lon: float,
    end_lat: float,   end_lon: float,
    distance_km: float, mode: str
) -> dict:
    return {
        "mode":          mode,
        "distance_km":   distance_km,
        "origin":        {"coordinate": {"lat": start_lat, "lon": start_lon}},
        "destination":   {"coordinate": {"lat": end_lat,   "lon": end_lon}}
    }


class RouteTool:
    def __init__(self):
        self.tools = [
            StructuredTool.from_function(coroutine=self.circular_random_route),
            StructuredTool.from_function(coroutine=self.circular_child_route),
            StructuredTool.from_function(coroutine=self.circular_running_route),
            StructuredTool.from_function(coroutine=self.oneway_shortest_route),
            StructuredTool.from_function(coroutine=self.oneway_random_route),
            StructuredTool.from_function(coroutine=self.oneway_child_route),
            StructuredTool.from_function(coroutine=self.oneway_running_route)
        ]
        self.tool_map = {t.name: t for t in self.tools}

    async def circular_random_route(
        self,
        start_lat: float,
        start_lon: float,
        distance_km: float = 3.0,
    ) -> dict:
        """
        출발지 주변을 랜덤하게 순환하는 경로를 생성합니다.
        특별한 조건 없이 자유롭게 산책하고 싶을 때 사용하세요.
        """
        ctx = _circular_context(start_lat, start_lon, distance_km, "circular_random")
        return await asyncio.to_thread(route_service.get_route, ctx)

    async def circular_child_route(
        self,
        start_lat: float,
        start_lon: float,
        distance_km: float = 3.0,
    ) -> dict:
        """
        어린이 친화 순환 경로를 생성합니다.
        어린이보호구역·안전한 길을 우선하며, 어린이 동반 산책에 적합합니다.
        """
        ctx = _circular_context(start_lat, start_lon, distance_km, "circular_child")
        return await asyncio.to_thread(route_service.get_route, ctx)

    async def circular_running_route(
        self,
        start_lat: float,
        start_lon: float,
        distance_km: float = 5.0,
    ) -> dict:
        """
        러닝·조깅에 적합한 순환 경로를 생성합니다.
        공원·하천 등 런닝 코스를 우선적으로 포함합니다.
        """
        ctx = _circular_context(start_lat, start_lon, distance_km, "circular_running")
        return await asyncio.to_thread(route_service.get_route, ctx)

    async def oneway_shortest_route(
        self,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
        distance_km: float = 3.0,
    ) -> dict:
        """
        출발지에서 목적지까지 최단 경로를 생성합니다.
        목적지가 정해져 있고 빠르게 이동하고 싶을 때 사용하세요.
        """
        ctx = _oneway_context(start_lat, start_lon, end_lat, end_lon, distance_km, "oneway_shortest")
        return await asyncio.to_thread(route_service.get_route, ctx)

    async def oneway_random_route(
        self,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
        distance_km: float = 3.0,
    ) -> dict:
        """
        출발지에서 목적지까지 목표 거리를 채우며 이동하는 경로를 생성합니다.
        목적지가 있지만 중간 경로를 다양하게 탐색하고 싶을 때 사용하세요.
        """
        ctx = _oneway_context(start_lat, start_lon, end_lat, end_lon, distance_km, "oneway_random")
        return await asyncio.to_thread(route_service.get_route, ctx)

    async def oneway_child_route(
        self,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
        distance_km: float = 3.0,
    ) -> dict:
        """
        어린이 친화 편도 경로를 생성합니다.
        어린이보호구역·안전한 길을 우선하며 목적지로 이동합니다.
        """
        ctx = _oneway_context(start_lat, start_lon, end_lat, end_lon, distance_km, "oneway_child")
        return await asyncio.to_thread(route_service.get_route, ctx)

    async def oneway_running_route(
        self,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
        distance_km: float = 5.0,
    ) -> dict:
        """
        러닝·조깅에 적합한 편도 경로를 생성합니다.
        공원·하천 런닝 코스를 우선 포함하며 목적지로 이동합니다.
        """
        ctx = _oneway_context(start_lat, start_lon, end_lat, end_lon, distance_km, "oneway_running")
        return await asyncio.to_thread(route_service.get_route, ctx)