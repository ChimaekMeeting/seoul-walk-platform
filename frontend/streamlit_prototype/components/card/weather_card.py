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
            "weather_info": {},
            "air_info": {},
        }


class WeatherCard:

    def fetch(self, lat: float, lng: float) -> dict:
        """
        위도·경도를 기반으로 캐싱된 날씨 정보를 반환합니다.
        """
        return _fetch_weather(lat, lng)

    def render(self, env: EnvData) -> None:
        """
        날씨 상세 정보와 대기질을 렌더링합니다.
        """
        w = env.weather_raw or {}
        a = env.air_raw or {}

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("강수형태", env.weather_status)
        with col2:
            temp = w.get("기온", "-")
            humi = w.get("습도", "")
            st.metric("기온 / 습도", f"{temp} / {humi}" if humi else temp)
        with col3:
            st.metric("대기질", env.air_status, env.air_msg)
        with col4:
            st.metric("초미세먼지", a.get("초미세먼지", "-"))
