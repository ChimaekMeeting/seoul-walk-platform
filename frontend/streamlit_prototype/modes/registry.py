"""
frontend/streamlit_prototype/modes/registry.py

앱에서 사용할 경로 모드 목록(ROUTE_MODES)을 정의하는 레지스트리.
새 경로 모드 추가 시 이 파일에 인스턴스를 등록한다.
"""
from frontend.streamlit_prototype.modes.base import BaseRouteMode
from frontend.streamlit_prototype.modes.circular import CircularMode
from frontend.streamlit_prototype.modes.oneway_shortest import OnewayShortestMode
from frontend.streamlit_prototype.modes.oneway_random import OnewayRandomMode

ROUTE_MODES: list[BaseRouteMode] = [
    CircularMode(),
    OnewayShortestMode(),
    OnewayRandomMode(),
]
