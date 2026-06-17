"""
frontend/streamlit_prototype/components/carousel/banner_data_carousel.py

배너 목록을 API를 통해 조회하고 렌더링하는 캐러셀 컴포넌트
날씨 상태와 현재 시각을 기반으로 배너 목록을 구성
"""
from datetime import datetime

import streamlit as st

from frontend.streamlit_prototype.api.banner_router import BannerRouter


class BannerDataCarousel:

    def __init__(self):
        self._router = BannerRouter()

    @st.cache_data(ttl=3600)
    def get_events_cached(_self) -> list:
        """
        input : 없음
        output: list (마라톤 이벤트 목록)

        GET /api/banner를 통해 이벤트 포함 배너 목록을 캐싱해 반환
        """
        return _self._router.get_banner_list("", "")

    def get_banner_list(self, weather: dict, hour: int | None = None) -> list:
        """
        input : weather (weather_status, weather_msg 포함 dict), hour (선택)
        output: [{"emoji", "text", "sub", ...}, ...]

        GET /api/banner 호출 후 배너 목록 반환
        hour 미입력 시 현재 시각 사용
        """
        if hour is None:
            hour = datetime.now().hour

        return self._router.get_banner_list(
            weather_status=weather.get("weather_status", ""),
            weather_msg=weather.get("weather_msg", ""),
            hour=hour,
        )
