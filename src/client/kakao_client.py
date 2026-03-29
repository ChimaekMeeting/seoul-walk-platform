from dotenv import load_dotenv
import os, httpx, asyncio

load_dotenv()

class KakaoClient:
    def __init__(self):
        self.KAKAO_API_KEY = os.getenv("KAKAO_API_KEY")
        self.base_url = "https://dapi.kakao.com/v2/local"
        self.headers= {
            "Authorization": f"KakaoAK {self.KAKAO_API_KEY}"
        }
        
        self.category_group_code = {
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

    async def get_address_from_coords(self, lat: float = 37.634496, lon: float = 126.832852):
        """
        경위도 좌표를 주소로 변환하는 함수입니다.
        """
        base_url = f"{self.base_url}/geo/coord2address.json"

        params = {
            "x": lon,
            "y": lat
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(base_url, params=params, headers=self.headers)
            data = response.json()
            print(data)
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

    async def get_address_from_keyword(self, keyword: str, lat: float, lon: float):
        """
        특정 키워드를 기반으로 주소를 반환하는 함수입니다.
        """
        base_url = f"{self.base_url}/search/keyword.json"

        params = {
            "query": keyword,
            "x": lon,
            "y": lat,
            "radius": 20000
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(base_url, params=params, headers=self.headers)
            return response.json()


    async def get_address_from_category(self, category: str, lat: float, lon: float):
        """
        특정 카테고리를 기반으로 주소를 반환하는 함수입니다.
        """
        base_url = f"{self.base_url}/search/category.json"

        params = {
            "query": self.category_group_code.get(category),
            "x": lon,
            "y": lat,
            "radius": 20000
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(base_url, params=params, headers=self.headers)
            return response.json()
        
# if __name__ == "__main__":
#     client = KakaoClient()
#     response = asyncio.run(client.get_address_from_coords())
#     print(response)