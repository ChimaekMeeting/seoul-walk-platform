from datetime import datetime

import streamlit as st

from src.infrastructure.external.client.marathon_client import MarathonClient
from src.service.route.banner_service import BannerService


class BannerDataCarousel:

    def __init__(self):
        self._service = BannerService(MarathonClient())

    @st.cache_data(ttl=3600)
    def get_events_cached(_self) -> list[dict]:
        return _self._service.get_events()

    def get_banner_list(self, weather: dict, hour: int | None = None) -> list:
        if hour is None:
            hour = datetime.now().hour

        status = weather.get("weather_status", "")
        msg    = weather.get("weather_msg", "")
        banners = []

        active_event = self._service.get_active_event()
        if active_event:
            banners.append(self._service._get_event_text(active_event))

        if self._service._is_hot(msg):
            if 6 <= hour < 9:
                banners.append(self._service.BANNERS["season"]["hot_morning"])
            elif self._service._is_humid(status):
                banners.append(self._service.BANNERS["season"]["hot_humid"])
            else:
                banners.append(self._service.BANNERS["season"]["hot_sunny"])

        keys = ["dog", "healing"] if hour < 17 else (["dog", "healing", "night"] if hour < 21 else ["night"])
        for key in keys:
            banners.append(self._service.BANNERS["fixed"][key])

        return banners
