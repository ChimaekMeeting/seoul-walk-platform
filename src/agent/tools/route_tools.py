import asyncio
from langchain_core.tools import StructuredTool

from src.interfaces.schema.walk_schema import WalkMode, Coordinate


class RouteTool:
    def __init__(self):
        from src.interfaces.dependencies import get_route_service
        self.route_service = get_route_service()
        self.tools = [
            StructuredTool.from_function(coroutine=self.circular_random_route),
            StructuredTool.from_function(coroutine=self.oneway_shortest_route),
            StructuredTool.from_function(coroutine=self.oneway_random_route),
        ]
        self.tool_map = {t.name: t for t in self.tools}

    async def circular_random_route(self, origin: Coordinate, target_km: float = 3.0, access_token: str = ""):
        """
        출발지 주변을 랜덤하게 순환하는 경로를 생성합니다.
        특별한 조건 없이 자유롭게 산책하고 싶을 때 사용하세요.
        """
        return await asyncio.to_thread(
            self.route_service.get_route, access_token, origin, None, target_km, WalkMode.CIRCULAR_RANDOM
        )

    async def oneway_shortest_route(self, origin: Coordinate, destination: Coordinate, access_token: str = ""):
        """
        출발지에서 목적지까지 최단 경로를 생성합니다.
        목적지가 정해져 있고 빠르게 이동하고 싶을 때 사용하세요.
        """
        return await asyncio.to_thread(
            self.route_service.get_route, access_token, origin, destination, None, WalkMode.ONEWAY_SHORTEST
        )

    async def oneway_random_route(self, origin: Coordinate, destination: Coordinate, target_km: float = 3.0, access_token: str = ""):
        """
        출발지에서 목적지까지 목표 거리를 채우며 이동하는 경로를 생성합니다.
        목적지가 있지만 중간 경로를 다양하게 탐색하고 싶을 때 사용하세요.
        """
        return await asyncio.to_thread(
            self.route_service.get_route, access_token, origin, destination, target_km, WalkMode.ONEWAY_RANDOM
        )