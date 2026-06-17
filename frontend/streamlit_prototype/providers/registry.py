"""
frontend/streamlit_prototype/providers/registry.py

앱에서 사용할 EnvProvider 구현체를 반환하는 팩토리 모듈
현재는 WeatherEnvProvider 고정 반환. 구현체 교체 시 이 파일만 수정
"""
from frontend.streamlit_prototype.providers.base import EnvProvider
from frontend.streamlit_prototype.providers.weather_api import WeatherEnvProvider


def build_provider() -> EnvProvider:
    """
    input : X
    output: EnvProvider

    WeatherEnvProvider 인스턴스를 생성하여 반환
    """
    return WeatherEnvProvider()
