import dataclasses

from frontend.streamlit_prototype.components.card.weather_card import _fetch_weather
from frontend.streamlit_prototype.components.carousel.banner_data_carousel import BannerDataCarousel
from frontend.streamlit_prototype.providers.base import EnvData, EnvProvider


class WeatherEnvProvider(EnvProvider):

    def __init__(self):
        self._banner_data = BannerDataCarousel()

    def fetch(self, lat: float, lng: float) -> EnvData:
        raw = _fetch_weather(lat, lng)
        return EnvData(
            weather_status=raw["weather_status"],
            weather_msg=raw["weather_msg"],
            air_status=raw["air_status"],
            air_msg=raw["air_msg"],
        )

    def get_banners(self, env: EnvData) -> list:
        return self._banner_data.get_banner_list(dataclasses.asdict(env))
