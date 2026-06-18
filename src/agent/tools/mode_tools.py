from langchain_core.tools import StructuredTool
from typing import Optional

from src.schema.prewalk_schema import Location, CircularPreference, OnewayPreference, OnewayShortestPreference
from src.interfaces.schema.walk_schema import CircularMode, OnewayMode


class ModeTool:
    def __init__(self):
        self.tools = [
            StructuredTool.from_function(self.select_circular),
            StructuredTool.from_function(self.select_oneway),
            StructuredTool.from_function(self.select_oneway_shortest),
        ]
        self.tool_map = {t.name: t for t in self.tools}

    def select_circular(
        self,
        origin: Location,
        mode: CircularMode,
        target_km: float,
        purpose: Optional[str] = None,
        profile_name: str = "default",
        child_friendly: bool = False,
        unsupported_preferences: Optional[list[str]] = None,
    ) -> CircularPreference:
        """
        순환 경로 모드를 선택합니다.
        mode: circular_random(기본 산책), circular_child(어린이 동반), circular_running(러닝·조깅)
        """
        return CircularPreference(
            origin=origin,
            mode=mode,
            target_km=target_km,
            purpose=purpose,
            profile_name=profile_name,
            child_friendly=child_friendly,
            unsupported_preferences=unsupported_preferences or [],
        )


    def select_oneway(
        self,
        origin: Location,
        destination: Location,
        mode: OnewayMode,
        target_km: float,
        purpose: Optional[str] = None,
        profile_name: str = "default",
        child_friendly: bool = False,
        unsupported_preferences: Optional[list[str]] = None,
    ) -> OnewayPreference:
        """
        편도 경로 모드를 선택합니다.
        mode: oneway_random(목적지 우회), oneway_child(어린이 동반), oneway_running(러닝·조깅)
        """
        return OnewayPreference(
            origin=origin,
            destination=destination,
            mode=mode,
            target_km=target_km,
            purpose=purpose,
            profile_name=profile_name,
            child_friendly=child_friendly,
            unsupported_preferences=unsupported_preferences or [],
        )


    def select_oneway_shortest(
        self,
        origin: Location,
        destination: Location,
        purpose: Optional[str] = None,
        profile_name: str = "default",
        child_friendly: bool = False,
        unsupported_preferences: Optional[list[str]] = None,
    ) -> OnewayShortestPreference:
        """
        목적지까지 최단 경로를 선택합니다.
        빠르게 이동하고 싶을 때 사용하세요.
        """
        return OnewayShortestPreference(
            origin=origin,
            destination=destination,
            purpose=purpose,
            profile_name=profile_name,
            child_friendly=child_friendly,
            unsupported_preferences=unsupported_preferences or [],
        )
