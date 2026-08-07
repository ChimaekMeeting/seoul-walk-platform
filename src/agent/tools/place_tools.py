from typing import Literal, Optional

from langchain_core.tools import StructuredTool

from src.infrastructure.external.client.kakao_client import KakaoClient
from src.infrastructure.external.schema.place_schema import PlaceSearchResult


class PlaceTool:
    def __init__(self):
        self._client = KakaoClient()
        self.tools = [
            StructuredTool.from_function(coroutine=self.get_address_from_keyword),
            StructuredTool.from_function(coroutine=self.get_address_from_category),
        ]
        self.tool_map = {t.name: t for t in self.tools}

    async def get_address_from_keyword(
        self,
        keyword: str,
        lat: float,
        lon: float,
        target: Optional[Literal["origin", "destination", "waypoint"]] = None,
        waypoint_index: Optional[int] = None,
    ) -> Optional[PlaceSearchResult]:
        """
        특정 키워드를 기반으로 주소를 반환하는 함수입니다.
        target이 'waypoint'면 몇 번째 경유지인지 waypoint_index로 지정하세요(0부터 시작).
        """
        return await self._client.get_address_from_keyword(keyword, lat, lon)

    async def get_address_from_category(
        self,
        category: str,
        lat: float,
        lon: float,
        target: Optional[Literal["origin", "destination", "waypoint"]] = None,
        waypoint_index: Optional[int] = None,
    ) -> Optional[PlaceSearchResult]:
        """
        특정 카테고리를 기반으로 주소를 반환하는 함수입니다.
        category 인자에는 반드시 다음 중 하나만 입력하세요:
        ['대형마트', '편의점', '어린이집, 유치원', '학교', '학원', '주유소, 충전소', '은행', '문화시설',
         '중개업소', '공공기관', '숙박', '음식점', '카페', '병원', '약국', '주차장', '지하철역', '관광명소']
        target이 'waypoint'면 몇 번째 경유지인지 waypoint_index로 지정하세요(0부터 시작).
        """
        return await self._client.get_address_from_category(category, lat, lon)
