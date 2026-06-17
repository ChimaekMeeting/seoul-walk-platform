import streamlit as st

from frontend.streamlit_prototype.modes.base import BaseRouteMode, RouteParams


class OnewayShortestMode(BaseRouteMode):
    label    = "최단 거리 편도 (목적지 직행)"
    mode_key = "oneway_shortest"

    def render_params(self) -> RouteParams:
        return self.default_params()
