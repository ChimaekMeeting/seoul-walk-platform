from langchain_core.output_parsers import StrOutputParser

from src.infrastructure.external.client.gpt_client import GPTClient
from src.infrastructure.external.client.kakao_client import KakaoClient
from src.infrastructure.external.client.weather_client import WeatherClient
from src.infrastructure.external.schema.weather_schema import EnvironmentInfo


class WeatherChecker(GPTClient):
    def __init__(self):
        super().__init__()
        self.weather_client = WeatherClient(KakaoClient())
        self.str_parser = StrOutputParser()

    async def run(self, lat: float, lon: float) -> EnvironmentInfo:
        """
        날씨·대기질 조회 후 GPT로 친절한 첫 인사 메시지를 생성하여 반환합니다.
        """
        weather_info = await self.weather_client.get_weather(lat, lon)
        air_info     = await self.weather_client.get_air_quality(lat, lon)

        response = await self.get_response(
            prompt_name="weather_checker",
            input_variables={
                "weather_info": str(weather_info),
                "air_info":     str(air_info),
            },
            parser=self.str_parser
        )

        # 날씨/대기질 조회가 실패하면 None이 반환될 수 있으므로 빈 dict로 보정합니다.
        return EnvironmentInfo(weather=weather_info or {}, air=air_info or {}), response
