from dotenv import load_dotenv
import os, httpx
from langchain_core.tools import tool
from typing import Literal

load_dotenv()

class KakaoClient:
    @tool  # function calling을 위해 @tool 추가
    async def get_address_from_coords(lat: float = 37.634496, lon: float = 126.832852):
        """
        경위도 좌표를 주소로 변환하는 함수입니다.
        """
        headers= {
            "Authorization": f"KakaoAK {os.getenv("KAKAO_API_KEY")}"
        }
        base_url = f"https://dapi.kakao.com/v2/local/geo/coord2address.json"

        params = {
            "x": lon,
            "y": lat
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(base_url, params=params, headers=headers)
            data = response.json()
            document = data.get("documents")[0]

            road_address = document.get("road_address")
            address = document.get("address")

            if road_address:
                return {
                    "place_address": road_address.get("address_name"),
                    "place_name": road_address.get("building_name", "현 위치"),
                    "place_lat": lat,
                    "place_lon": lon
                }
            else:
                return {
                    "place_address": address.get("address_name"),
                    "place_name": address.get("building_name", "현 위치"),
                    "place_lat": lat,
                    "place_lon": lon
                }

    @tool
    async def get_address_from_keyword(keyword: str, lat: float, lon: float, target: Literal["origin", "destination"]):
        """
        특정 키워드를 기반으로 주소를 반환하는 함수입니다.
        """
        headers= {
            "Authorization": f"KakaoAK {os.getenv("KAKAO_API_KEY")}"
        }
        base_url = f"https://dapi.kakao.com/v2/local/search/keyword.json"

        params = {
            "query": keyword,
            "x": lon,
            "y": lat,
            "radius": 20000,
            "size": 3
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(base_url, params=params, headers=headers)
            return response.json()

    @tool
    async def get_address_from_category(category: str, lat: float, lon: float, target: Literal["origin", "destination"]):
        """
        특정 카테고리를 기반으로 주소를 반환하는 함수입니다.
        category 인자에는 반드시 다음 중 하나만 입력하세요:
        ['대형마트', '편의점', '어린이집, 유치원', '학교', '학원', '주유소, 충전소', '은행', '문화시설', '중개업소', '공공기관', '숙박', '음식점', '카페', '병원', '약국', '주차장', '지하철역', '관광명소']
        """
        headers= {
            "Authorization": f"KakaoAK {os.getenv("KAKAO_API_KEY")}"
        }
        base_url = f"https://dapi.kakao.com/v2/local/search/category.json"

        category_group_code = {
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
            "약국": "PM9"
        }

        params = {
            "query": category_group_code.get(category),
            "x": lon,
            "y": lat,
            "radius": 20000,
            "size": 3,
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(base_url, params=params, headers=headers)
            return response.json()