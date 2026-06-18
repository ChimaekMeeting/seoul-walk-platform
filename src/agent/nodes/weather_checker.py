from src.infrastructure.external.client.weather_client import WeatherClient
from src.infrastructure.external.schema.weather_schema import EnvironmentInfo
from typing import Tuple
import textwrap


class WeatherChecker:
    def __init__(self):
        self._client = WeatherClient()
        self.init_message = textwrap.dedent("""
            오늘 어떤 산책이 필요하세요? 기분 전환, 조용한 길, 땀 안 나는 짧은 코스, 아이와 함께, 평지 위주처럼 편하게 말씀해 주세요.
            출발지는 현재 위치를 기준으로 잡고, 목적지가 필요할 때만 제가 다시 물어볼게요.
        """).strip()

    async def generate_init_message(self, lat: float, lon: float) -> Tuple[EnvironmentInfo, str]:
        """날씨 조회 후 초기 메시지를 조립하여 반환"""
        weather_data = await self._client.get_environment_info(lat, lon)
        weather_msg = weather_data.display_msg
        return weather_data, f"{weather_msg}\n{self.init_message}"
