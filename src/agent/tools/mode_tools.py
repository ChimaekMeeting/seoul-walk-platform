from langchain_core.tools import StructuredTool

from src.schema.prewalk_schema import Location, CircularPreference, OnewayPreference, OnewayShortestPreference


class ModeTool:
    def __init__(self):
        self.tools = [
            StructuredTool.from_function(self.select_circular),
            StructuredTool.from_function(self.select_oneway),
            StructuredTool.from_function(self.select_oneway_shortest),
            StructuredTool.from_function(self.select_none),
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

    def select_none(self) -> None:
        """
        산책 경로 생성 요청이 아닌 경우에 호출하세요.
        날씨·시간·잡담·인사·기타 질문 등 산책 의도가 없을 때 반드시 이 도구를 선택하고,
        목적지나 출발지를 절대 지어내지 마세요.
        """
        return None
