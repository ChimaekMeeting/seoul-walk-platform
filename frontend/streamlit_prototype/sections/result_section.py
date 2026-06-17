"""
frontend/streamlit_prototype/sections/result_section.py

경로 계산 결과 패널과 경로 추천 버튼을 렌더링하는 result 섹션
"""

import streamlit as st

from frontend.streamlit_prototype.bootstrap import AppContext
from frontend.streamlit_prototype.modes.base import RouteParams
from frontend.streamlit_prototype.sections.sidebar import SidebarConfig


def render_result(
    ctx:     AppContext,
    sidebar: SidebarConfig,
    params:  RouteParams,
    lat:     float,
    lng:     float,
) -> None:
    # render_result
    """
    input : ctx(AppContext), sidebar(SidebarConfig), params(RouteParams), lat(float), lng(float)
    output: X

    session_state에 route_result가 있으면 결과 패널을 렌더링
    walk_route_button을 통해 경로 추천 버튼 UI를 렌더링
    """
    if st.session_state.get("route_result"):
        ctx.walk_result_panel.render(st.session_state.route_result)

    ctx.walk_route_button.render(
        sidebar.input_mode, params.mode_key, params.distance_km,
        params.child_friendly, params.safety_w, params.nature_w, lat, lng
    )
