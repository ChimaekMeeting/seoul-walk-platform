import httpx

from frontend.streamlit_prototype.api.base_url import base_url

class WeatherRouter:
    def __init__(self):
        self.base_url = f"{base_url}/api/weather"

    async def get_weather(self, lat: float, lon: float):
        """
        위도와 경도를 기반으로 현재 날씨 정보를 조회하는 API를 호출합니다.
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            params = {
                "lat": lat,
                "lon": lon
            }
            response = await client.get(self.base_url, params=params)
            return response.json()