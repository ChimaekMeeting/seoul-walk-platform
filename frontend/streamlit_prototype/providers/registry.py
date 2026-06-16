from frontend.streamlit_prototype.providers.base import EnvProvider
from frontend.streamlit_prototype.providers.weather_api import WeatherEnvProvider


def build_provider() -> EnvProvider:
    return WeatherEnvProvider()
