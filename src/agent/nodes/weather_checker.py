from langchain_core.output_parsers import StrOutputParser

from src.infrastructure.external.client.gpt_client import GPTClient
from src.infrastructure.external.client.weather_client import WeatherClient
from src.infrastructure.external.schema.weather_schema import EnvironmentInfo


class WeatherChecker(GPTClient):
    def __init__(self, weather_client: WeatherClient):
        super().__init__()
        self.weather_client = weather_client
        self.str_parser = StrOutputParser()

    async def run(self, lat: float, lon: float) -> tuple[EnvironmentInfo, str]:
        """
        날씨·대기질 조회 후 LLM으로 친절한 첫 인사 메시지를 생성하여 반환합니다.
        """
        weather_info = await self.weather_client.get_weather(lat, lon)
        air_info     = await self.weather_client.get_air_quality(lat, lon)

        res = await self.get_response(
            prompt_name="weather_checker",
            input_variables={
                "weather_info": str(weather_info),
                "air_info":     str(air_info),
            },
            parser=self.str_parser
        )

        return EnvironmentInfo(weather=weather_info or {}, air=air_info or {}), res
