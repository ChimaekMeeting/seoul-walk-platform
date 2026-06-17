from frontend.streamlit_prototype.modes.base import BaseRouteMode, RouteParams
import streamlit as st


class CircularRunningMode(BaseRouteMode):
    label    = "러닝·조깅 순환"
    mode_key = "circular_running"

    def render_params(self) -> RouteParams:
        return RouteParams(
            mode_key  = self.mode_key,
            target_km = st.sidebar.slider("목표 거리 (km)", 1.0, 15.0, 5.0, 0.5, key="target_km"),
        )
