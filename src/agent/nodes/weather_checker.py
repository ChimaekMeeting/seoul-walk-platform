import logging

from langchain_core.output_parsers import StrOutputParser

from src.infrastructure.external.client.gpt_client import GPTClient
from src.infrastructure.external.client.weather_client import WeatherClient
from src.infrastructure.cache.repository.weather_cache_repository import WeatherCacheRepository

logger = logging.getLogger(__name__)


class WeatherChecker(GPTClient):
    def __init__(self, weather_client: WeatherClient):
        super().__init__()
        self.weather_client = weather_client
        self.str_parser = StrOutputParser()

    async def run(self, lat: float, lon: float) -> str:
        """
        날씨·대기질 조회 후 LLM으로 친절한 첫 인사 메시지를 생성하여 반환합니다.
        같은 기상청 격자(nx, ny) 안에서는 Valkey에 30분간 캐싱된 값을 재사용합니다.
        """
        nx, ny = self.weather_client.get_nx_and_ny(lat, lon)

        try:
            weather_info = await WeatherCacheRepository.get_weather(nx, ny)
            if weather_info is None:
                weather_info = await self.weather_client.get_weather(lat, lon)
                if weather_info:
                    await WeatherCacheRepository.save_weather(nx, ny, weather_info)
        except Exception:
            logger.exception("weather_api_error | lat=%s | lon=%s", lat, lon)
            weather_info = None

        try:
            air_info = await WeatherCacheRepository.get_air_quality(nx, ny)
            if air_info is None:
                air_info = await self.weather_client.get_air_quality(lat, lon)
                if air_info:
                    await WeatherCacheRepository.save_air_quality(nx, ny, air_info)
        except Exception:
            logger.exception("air_quality_api_error | lat=%s | lon=%s", lat, lon)
            air_info = None

        try:
            res = await self.get_response(
                prompt_name="weather_checker",
                input_variables={
                    "weather_info": str(weather_info),
                    "air_info":     str(air_info),
                },
                parser=self.str_parser
            )
        except Exception:
            logger.exception("weather_checker_llm_error | lat=%s | lon=%s", lat, lon)
            res = "안녕하세요! 오늘 어디로 산책을 떠나볼까요?"

        return res
