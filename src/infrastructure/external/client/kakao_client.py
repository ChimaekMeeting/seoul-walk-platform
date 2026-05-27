from dotenv import load_dotenv
import os, httpx
from typing import Literal, Optional

from src.infrastructure.external.schema import (
    PlaceInfo,
    PlaceSearchResult
)

load_dotenv()

CATEGORY_GROUP_CODE = {
    "대형마트": "MT1",
    "편의점": "CS2",
    "어린이집, 유치원": "PS3",
    "학교": "SC4",
    "학원": "AC5",
    "주차장": "PK6",
    "주유소, 충전소": "OL7",
    "지하철역": "SW8",
    "은행": "BK9",
    "문화시설": "CT1",
    "중개업소": "AG2",
    "공공기관": "PO3",
    "관광명소": "AT4",
    "숙박": "AD5",
    "음식점": "FD6",
    "카페": "CE7",
    "병원": "HP8",
    "약국": "PM9",
}

class KakaoClient:
    def __init__(self):
        self.KAKAO_API_KEY = os.getenv("KAKAO_API_KEY")

    def get_headers(self) -> dict:
        return {"Authorization": f"KakaoAK {self.KAKAO_API_KEY}"}

    async def get_address_from_coords(self, lat: float, lon: float) -> PlaceInfo:
        """
        경위도 좌표를 주소로 변환합니다.
        """
        async with httpx.AsyncClient() as client:
            res = await client.get(
                "https://dapi.kakao.com/v2/local/geo/coord2address.json",
                params={"x": lon, "y": lat},
                headers=self.get_headers(),
            )
            docs = res.json().get("documents")[0]
            road_address = docs.get("road_address")
            address = docs.get("address")

            if road_address:
                return PlaceInfo(
                    place_address=road_address.get("address_name"),
                    place_name=road_address.get("building_name") or "현 위치",
                    place_lat=lat,
                    place_lon=lon,
                )
            return PlaceInfo(
                place_address=address.get("address_name"),
                place_name=address.get("building_name") or "현 위치",
                place_lat=lat,
                place_lon=lon,
            )

    async def get_address_from_keyword(
        self,
        keyword: str,
        lat: float,
        lon: float,
        target: Optional[Literal["origin", "destination"]] = None,
    ) -> Optional[PlaceSearchResult]:
        """
        특정 키워드를 기반으로 주소를 반환합니다.
        """
        return await self.search_places(lat=lat, lon=lon, keyword=keyword)

    async def get_address_from_category(
        self,
        category: str,
        lat: float,
        lon: float,
        target: Optional[Literal["origin", "destination"]] = None,
    ) -> Optional[PlaceSearchResult]:
        """
        특정 카테고리를 기반으로 주소를 반환합니다.
        category 인자에는 반드시 다음 중 하나만 입력하세요:
        ['대형마트', '편의점', '어린이집, 유치원', '학교', '학원', '주유소, 충전소', '은행', '문화시설',
         '중개업소', '공공기관', '숙박', '음식점', '카페', '병원', '약국', '주차장', '지하철역', '관광명소']
        """
        code = CATEGORY_GROUP_CODE.get(category)
        return await self.search_places(lat=lat, lon=lon, category_code=code)

    async def search_places(
        self,
        lat: float,
        lon: float,
        page: int = 1,
        radius: int = 20000,
        size: int = 3,
        category_code: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> Optional[PlaceSearchResult]:
        """
        카카오 로컬 API를 통해 주변 장소(카테고리/키워드)를 검색합니다.
        keyword가 있으면 키워드 검색, 없으면 category_code로 카테고리 검색을 수행합니다.
        """
        is_keyword = bool(keyword)
        url = (
            "https://dapi.kakao.com/v2/local/search/keyword.json"
            if is_keyword
            else "https://dapi.kakao.com/v2/local/search/category.json"
        )
        params: dict = {"y": lat, "x": lon, "radius": radius, "page": page, "size": size}
        if is_keyword:
            params["query"] = keyword
        else:
            params["category_group_code"] = category_code

        async with httpx.AsyncClient() as client:
            res = await client.get(url, headers=self.get_headers(), params=params, timeout=5)
            return PlaceSearchResult(**res.json())
        return None

    async def get_kakao_geocode(self, address: str) -> Optional[tuple[float, float]]:
        """
        텍스트 주소를 위경도 좌표 [x, y]로 변환합니다.
        """
        async with httpx.AsyncClient() as client:
            res = await client.get(
                "https://dapi.kakao.com/v2/local/search/address.json",
                headers=self.get_headers(),
                params={"query": address},
            )
            docs = res.json().get("documents")
            return (float(docs[0]["x"]), float(docs[0]["y"]))
        return None
