from langchain_core.tools import StructuredTool
from typing import Optional

from src.schema.prewalk_schema import (
    Location,
    CircularPreference,
    OnewayPreference,
    OnewayShortestPreference,
    GpsArtPreference,
)


class ModeTool:
    def __init__(self):
        self.tools = [
            StructuredTool.from_function(self.select_circular),
            StructuredTool.from_function(self.select_oneway),
            StructuredTool.from_function(self.select_oneway_shortest),
            StructuredTool.from_function(self.select_gps_art),
        ]
        self.tool_map = {t.name: t for t in self.tools}

    def select_circular(self, origin: Location, target_km: float) -> CircularPreference:
        """
        출발지 주변을 자유롭게 순환하는 산책 경로(circular_random)를 선택합니다.
        목적지 없이 목표 거리만큼 걷고 싶을 때 사용하세요.
        """
        return CircularPreference(origin=origin, target_km=target_km)


    def select_oneway(self, origin: Location, destination: Location, target_km: float) -> OnewayPreference:
        """
        목적지까지 목표 거리를 채우며 우회하는 편도 경로(oneway_random)를 선택합니다.
        목적지가 있지만 중간 경로를 다양하게 탐색하고 싶을 때 사용하세요.
        """
        return OnewayPreference(origin=origin, destination=destination, target_km=target_km)


    def select_oneway_shortest(self, origin: Location, destination: Location) -> OnewayShortestPreference:
        """
        목적지까지 최단 경로를 선택합니다.
        빠르게 이동하고 싶을 때 사용하세요.
        """
        return OnewayShortestPreference(origin=origin, destination=destination)

    def select_gps_art(self, origin: Location, shape: str, target_km: Optional[float] = None) -> GpsArtPreference:
        """
        미리 준비된 도형 템플릿을 따라 순환하는 경로(gps_art)를 선택합니다.
        사용자가 "강아지" 모양으로 걷고 싶다고 말할 때 사용하세요. 현재는 "강아지"만 지원합니다.
        좌표는 직접 만들지 말고 shape 이름만 정확히 반환하세요.
        """
        return GpsArtPreference(origin=origin, shape=shape, target_km=target_km)
