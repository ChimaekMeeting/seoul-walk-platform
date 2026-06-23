"""
frontend/streamlit_prototype/components/carousel/banner_data_carousel.py

배너 목록을 API를 통해 조회하고 렌더링하는 캐러셀 컴포넌트
위치 좌표를 기반으로 배너 목록을 구성
"""
from datetime import datetime

import streamlit as st

from frontend.streamlit_prototype.api.banner_router import BannerRouter


class BannerDataCarousel:

    def __init__(self):
        self._router = BannerRouter()

    def get_banner_list(self, lat: float, lon: float, hour: int | None = None) -> list:
        """
        input : lat (float), lon (float), hour (선택)
        output: [{"emoji", "text", "sub", ...}, ...]

        GET /api/banner 호출 후 배너 목록 반환
        hour 미입력 시 현재 시각 사용
        """
        if hour is None:
            hour = datetime.now().hour

        return self._router.get_banner_list(lat=lat, lon=lon, hour=hour)
