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


def _khai_to_grade(khai_str: str) -> str:
    """통합대기환경지수(숫자 문자열) → 등급 문자열 변환"""
    try:
        v = int(float(khai_str))
    except (TypeError, ValueError):
        return ""
    if v <= 50:   return "좋음"
    if v <= 100:  return "보통"
    if v <= 250:  return "나쁨"
    return "매우나쁨"


def _pm10_to_grade(pm_str: str) -> str:
    """미세먼지(PM10) 수치 문자열 → 등급 문자열 변환 (KhaiValue 없을 때 폴백)"""
    try:
        v = int(float(pm_str.replace("㎍/㎥", "").strip()))
    except (TypeError, ValueError):
        return "알 수 없음"
    if v <= 30:   return "좋음"
    if v <= 80:   return "보통"
    if v <= 150:  return "나쁨"
    return "매우나쁨"


class WeatherEnvProvider(EnvProvider):

    def __init__(self):
        self._banner_data = BannerDataCarousel()

    def fetch(self, lat: float, lng: float) -> EnvData:
        """
        input : lat (float), lng (float)
        output: EnvData

        /api/weather 호출 결과를 EnvData로 변환하여 반환한다.
        새 응답 포맷: {"weather_info": {...}, "air_info": {...}}
        """
        raw = _fetch_weather(lat, lng)
        weather = raw.get("weather_info") or {}
        air     = raw.get("air_info") or {}

        weather_status = weather.get("강수형태", "맑음")
        weather_msg    = weather.get("기온", "")
        air_status     = _khai_to_grade(air.get("통합대기환경지수", "")) or _pm10_to_grade(air.get("미세먼지", ""))
        air_msg        = air.get("미세먼지", "")

        return EnvData(
            weather_status=weather_status,
            weather_msg=weather_msg,
            air_status=air_status,
            air_msg=air_msg,
            weather_raw=weather,
            air_raw=air,
        )

    def get_banners(self, env: EnvData, lat: float = 0.0, lon: float = 0.0) -> list:
        """
        input : env (EnvData), lat (float), lon (float)
        output: list

        위치 좌표를 기반으로 배너 리스트를 조회하여 반환
        """
        return self._banner_data.get_banner_list(lat=lat, lon=lon)
