"""
frontend/streamlit_prototype/modes/oneway_shortest.py

최단 거리 편도 모드 구현체
출발지에서 도착지까지 최단 경로로 직행
거리 입력이 불필요하므로 render_params()는 UI 없이 default_params()를 반환
"""
import streamlit as st

from frontend.streamlit_prototype.modes.base import BaseRouteMode, RouteParams

class OnewayShortestMode(BaseRouteMode):
    label    = "최단 거리 편도 (목적지 직행)"
    mode_key = "oneway_shortest"
    needs_destination = True

    def render_params(self) -> RouteParams:
        return self.default_params()
