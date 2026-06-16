import streamlit as st

from frontend.streamlit_prototype.components.map.walk_route_map import WalkRouteMap


def setup_page(walk_route_map: WalkRouteMap) -> None:
    st.set_page_config(page_title="서울 산책 플랫폼", page_icon="🚶", layout="wide")
    st.title("🚶 서울시 산책 경로 추천")
    st.markdown("---")
    walk_route_map.inject_geolocation_js()
