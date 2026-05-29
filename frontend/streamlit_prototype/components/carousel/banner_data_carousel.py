from datetime import datetime

import streamlit as st

from src.service.route.banner_service import (
    get_events,
    get_active_event,
    _get_event_text,
    BANNERS,
    _is_hot,
    _is_humid,
)


class BannerDataCarousel:

    @st.cache_data(ttl=3600)
    def get_events_cached(_self) -> list[dict]:
        """
        이벤트 목록을 1시간 동안 캐싱하여 반환합니다.
        """
        return get_events()

    def get_banner_list(self, weather: dict, hour: int | None = None) -> list:
        """
        날씨 상태와 현재 시각을 기반으로 표시할 배너 목록을 생성합니다.
        """
        if hour is None:
            hour = datetime.now().hour

        status = weather.get("weather_status", "")
        msg    = weather.get("weather_msg", "")
        banners = []

        active_event = get_active_event()
        if active_event:
            banners.append(_get_event_text(active_event))

        if _is_hot(msg):
            if 6 <= hour < 9:
                banners.append(BANNERS["season"]["hot_morning"])
            elif _is_humid(status):
                banners.append(BANNERS["season"]["hot_humid"])
            else:
                banners.append(BANNERS["season"]["hot_sunny"])

        keys = ["dog", "healing"] if hour < 17 else (["dog", "healing", "night"] if hour < 21 else ["night"])
        for key in keys:
            banners.append(BANNERS["fixed"][key])

        return banners
