"""
frontend/streamlit_prototype/providers/weather_api.py

EnvProvider의 날씨 API 기반 구현체

weather_card의 _fetch_weather()를 통해
FastAPI /api/weather 엔드포인트를 호출 -> 응답을 EnvData로 변환
"""
import dataclasses

from frontend.streamlit_prototype.components.card.weather_card import _fetch_weather
from frontend.streamlit_prototype.components.carousel.banner_data_carousel import BannerDataCarousel
from frontend.streamlit_prototype.providers.base import EnvData, EnvProvider


class WeatherEnvProvider(EnvProvider):

    def __init__(self):
        self._banner_data = BannerDataCarousel()

    def fetch(self, lat: float, lng: float) -> EnvData:
        """
        input : lat (float), lng (float)
        output: EnvData

        /api/weather 호출 결과를 EnvData로 변환하여 반환한다.
        """
        raw = _fetch_weather(lat, lng)
        return EnvData(
            weather_status=raw["weather_status"],
            weather_msg=raw["weather_msg"],
            air_status=raw["air_status"],
            air_msg=raw["air_msg"],
        )

    def get_banners(self, env: EnvData) -> list:
        """
        input : env (EnvData)
        output: list

        EnvData를 dict로 변환해 BannerDataCarousel에서 배너 리스트를 조회하여 반환
        """
        return self._banner_data.get_banner_list(dataclasses.asdict(env))
