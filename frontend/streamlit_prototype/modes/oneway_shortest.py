from frontend.streamlit_prototype.modes.base import BaseRouteMode


class OnewayShortestMode(BaseRouteMode):
    label    = "최단 거리 편도 (목적지 직행)"
    mode_key = "oneway_shortest"
