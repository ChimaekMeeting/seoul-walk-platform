"""
frontend/streamlit_prototype/sections/page_setup.py

Streamlit 페이지 기본 설정(제목, 아이콘, 레이아웃)과 GPS 위치 수집 JavaScript를 초기화하는 섹션
"""

import streamlit as st

from frontend.streamlit_prototype.components.map.walk_route_map import WalkRouteMap


def setup_page(walk_route_map: WalkRouteMap) -> None:
    """
    input : walk_route_map (WalkRouteMap)
    output: X

    페이지 설정을 적용하고 geolocation JS를 삽입
    브라우저 GPS 좌표를 URL 쿼리 파라미터(lat, lng)로 설정
    """
    st.set_page_config(page_title="서울 산책 플랫폼", page_icon="🚶", layout="wide")
    st.title("🚶 서울시 산책 경로 추천")
    st.markdown("---")
    walk_route_map.inject_geolocation_js()
