from langchain_core.tools import StructuredTool
from typing import List, Optional

from src.schema.prewalk_schema import (
    Location,
    CircularPreference,
    OnewayPreference,
    OnewayShortestPreference,
    GPSArtPreference,
    WayPointPreference,
    WaypointLegPreference,
)

class ModeTool:
    def __init__(self):
        self.tools = [
            StructuredTool.from_function(self.select_circular),
            StructuredTool.from_function(self.select_oneway),
            StructuredTool.from_function(self.select_oneway_shortest),
            StructuredTool.from_function(self.select_gps_art),
            StructuredTool.from_function(self.select_waypoint),
        ]
        self.tool_map = {t.name: t for t in self.tools}

    def select_circular(self, origin: Optional[Location] = None, target_km: Optional[float] = None) -> CircularPreference:
        """
        출발지 주변을 자유롭게 순환하는 산책 경로(circular_random)를 선택합니다.
        목적지 없이 목표 거리만큼 걷고 싶을 때 사용하세요.
        """
        return CircularPreference(origin=origin, target_km=target_km)


    def select_oneway(self, origin: Optional[Location] = None, destination: Optional[Location] = None, target_km: Optional[float] = None) -> OnewayPreference:
        """
        목적지까지 목표 거리를 채우며 우회하는 편도 경로(oneway_random)를 선택합니다.
        목적지가 있지만 중간 경로를 다양하게 탐색하고 싶을 때 사용하세요.
        """
        return OnewayPreference(origin=origin, destination=destination, target_km=target_km)


    def select_oneway_shortest(self, origin: Optional[Location] = None, destination: Optional[Location] = None) -> OnewayShortestPreference:
        """
        목적지까지 최단 경로를 선택합니다.
        빠르게 이동하고 싶을 때 사용하세요.
        """
        return OnewayShortestPreference(origin=origin, destination=destination)

    def select_gps_art(self, origin: Optional[Location] = None, shape: Optional[str] = None, target_km: Optional[float] = None) -> GPSArtPreference:
        """
        GPS Art를 기반으로 거리를 채우는 순환 경로를 선택합니다.
        특정 모양으로 이동하고 싶을 때 사용하세요.
        """
        return GPSArtPreference(origin=origin, shape=shape, target_km=target_km)

    def select_waypoint(
        self,
        origin: Optional[Location] = None,
        waypoints: Optional[List[Location]] = None,
        destination: Optional[Location] = None,
        legs: Optional[List[WaypointLegPreference]] = None,
    ) -> WayPointPreference:
        """
        경유지를 하나 이상 거쳐가는 경로(waypoint)를 선택합니다.
        출발지 -> waypoints[0] -> ... -> waypoints[-1] -> destination 순으로 이동하며,
        legs[i]는 그 순서상 i번째 구간의 이동 방식입니다. 사용자가 구간별 이동 방식을
        언급하지 않으면 legs는 비워두세요(각 구간은 최단 경로로 처리됩니다).
        순환 코스를 원하면 destination을 origin과 동일한 위치로 지정하세요.
        """
        return WayPointPreference(
            origin=origin,
            waypoints=waypoints or [],
            destination=destination,
            legs=legs or [],
        )