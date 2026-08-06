import asyncio
from typing import Optional
from langchain_core.tools import StructuredTool

from src.interfaces.schema.walk_schema import WalkMode, Coordinate
from src.route_engine.profiles import ScoringProfile
from src.schema.route_schema import Weights
from src.service.route.gps_art_service import GpsArtService


class RouteTool:
    def __init__(self, gps_art_service: GpsArtService):
        from src.interfaces.dependencies import get_route_service
        self.route_service = get_route_service()
        self.gps_art_service = gps_art_service

        self.tools = [
            StructuredTool.from_function(coroutine=self.circular_random_route),
            StructuredTool.from_function(coroutine=self.oneway_shortest_route),
            StructuredTool.from_function(coroutine=self.oneway_random_route),
            StructuredTool.from_function(coroutine=self.gps_art_route),
        ]
        self.tool_map = {t.name: t for t in self.tools}

    async def circular_random_route(self, origin: Coordinate, target_km: float = 3.0, access_token: str = "", custom_weights: Optional[Weights] = None, profile: Optional[ScoringProfile] = None):
        """
        출발지 주변을 랜덤하게 순환하는 경로를 생성합니다.
        특별한 조건 없이 자유롭게 산책하고 싶을 때 사용하세요.
        """
        return await asyncio.to_thread(
            self.route_service.get_route, access_token, origin, None, target_km, WalkMode.CIRCULAR_RANDOM, custom_weights, profile
        )

    async def oneway_shortest_route(self, origin: Coordinate, destination: Coordinate, access_token: str = "", custom_weights: Optional[Weights] = None, profile: Optional[ScoringProfile] = None):
        """
        출발지에서 목적지까지 최단 경로를 생성합니다.
        목적지가 정해져 있고 빠르게 이동하고 싶을 때 사용하세요.
        """
        return await asyncio.to_thread(
            self.route_service.get_route, access_token, origin, destination, None, WalkMode.ONEWAY_SHORTEST, custom_weights, profile
        )

    async def oneway_random_route(self, origin: Coordinate, destination: Coordinate, target_km: float = 3.0, access_token: str = "", custom_weights: Optional[Weights] = None, profile: Optional[ScoringProfile] = None):
        """
        출발지에서 목적지까지 목표 거리를 채우며 이동하는 경로를 생성합니다.
        목적지가 있지만 중간 경로를 다양하게 탐색하고 싶을 때 사용하세요.
        """
        return await asyncio.to_thread(
            self.route_service.get_route, access_token, origin, destination, target_km, WalkMode.ONEWAY_RANDOM, custom_weights, profile
        )

    async def gps_art_route(self, origin: Coordinate, shape: str, target_km: float = 3.0, access_token: str = "", custom_weights: Optional[Weights] = None, profile: Optional[ScoringProfile] = None):
        """
        출발지 주변에 지정한 도형(shape) 모양을 그리는 경로를 생성합니다.
        하트, 별 등 특정 모양을 그리며 걷고 싶을 때 사용하세요.
        """
        shape_points = await self.gps_art_service.get_shape_points(access_token, shape)

        return await asyncio.to_thread(
            self.route_service.get_route, access_token, origin, None, target_km, WalkMode.GPS_ART, custom_weights, profile, shape_points
        )
