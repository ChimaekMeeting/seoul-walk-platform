import streamlit as st

from src.service.banner_service import get_events


@st.cache_data(ttl=3600)
def get_events_cached() -> list[dict]:
    """이벤트 목록을 1시간 캐싱합니다."""
    return get_events()
