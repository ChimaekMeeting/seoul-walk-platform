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
    if st.session_state.get("route_result"):
        ctx.walk_result_panel.render(st.session_state.route_result)

    ctx.walk_route_button.render(
        sidebar.input_mode, params.mode_key, params.distance_km,
        params.child_friendly, lat, lng
    )
