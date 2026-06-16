from frontend.streamlit_prototype.modes.base import BaseRouteMode
from frontend.streamlit_prototype.modes.circular import CircularMode
from frontend.streamlit_prototype.modes.oneway_shortest import OnewayShortestMode
from frontend.streamlit_prototype.modes.oneway_random import OnewayRandomMode

ROUTE_MODES: list[BaseRouteMode] = [
    CircularMode(),
    OnewayShortestMode(),
    OnewayRandomMode(),
]
