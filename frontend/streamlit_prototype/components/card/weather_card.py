import asyncio

import streamlit as st

from frontend.streamlit_prototype.api.weather_router import WeatherRouter
from frontend.streamlit_prototype.providers.base import EnvData


@st.cache_data(ttl=300)
def _fetch_weather(lat: float, lng: float) -> dict:
    """
    WeatherRouter를 통해 날씨 정보를 300초 동안 캐싱하여 반환합니다.
    """
    try:
        router = WeatherRouter()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        data = loop.run_until_complete(router.get_weather(lat, lng))
        return data
    except Exception:
        return {
            "weather_status": "알 수 없음",
            "weather_msg": "서버 연결 실패",
            "air_status": "알 수 없음",
            "air_msg": "",
        }


class WeatherCard:

    def fetch(self, lat: float, lng: float) -> dict:
        """
        위도·경도를 기반으로 캐싱된 날씨 정보를 반환합니다.
        """
        return _fetch_weather(lat, lng)

    def render(self, env: EnvData) -> None:
        """
        날씨, 미세먼지, 추천 경로 수 지표를 3열로 렌더링합니다.
        """
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("현재 날씨", env.weather_status, env.weather_msg)
        with col2:
            st.metric("미세먼지", env.air_status, env.air_msg)
        with col3:
            st.metric("추천 경로", "3개", "평균 3.2km")
