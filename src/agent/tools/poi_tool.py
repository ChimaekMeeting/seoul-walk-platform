from typing import Literal, Optional

from langchain_core.tools import tool

from src.client.kakao_client import KakaoClient

_client = KakaoClient()


@tool
async def get_address_from_coords(lat: float = 37.634496, lon: float = 126.832852) -> dict:
    """경위도 좌표를 주소로 변환하는 함수입니다."""
    return await _client.get_address_from_coords(lat, lon)


@tool
async def get_address_from_keyword(
    keyword: str,
    lat: float,
    lon: float,
    target: Optional[Literal["origin", "destination"]] = None,
) -> dict:
    """특정 키워드를 기반으로 주소를 반환하는 함수입니다."""
    return await _client.get_address_from_keyword(keyword, lat, lon, target)


@tool
async def get_address_from_category(
    category: str,
    lat: float,
    lon: float,
    target: Optional[Literal["origin", "destination"]] = None,
) -> dict:
    """
    특정 카테고리를 기반으로 주소를 반환하는 함수입니다.
    category 인자에는 반드시 다음 중 하나만 입력하세요:
    ['대형마트', '편의점', '어린이집, 유치원', '학교', '학원', '주유소, 충전소', '은행', '문화시설',
     '중개업소', '공공기관', '숙박', '음식점', '카페', '병원', '약국', '주차장', '지하철역', '관광명소']
    """
    return await _client.get_address_from_category(category, lat, lon, target)
