"""
frontend/streamlit_prototype/modes/oneway_random.py

거리 설정 편도 모드 구현체
출발지에서 도착지까지 목표 거리에 맞게 우회 경로를 생성
render_params()는 BaseRouteMode 기본 구현(km 슬라이더)을 사용
"""
from frontend.streamlit_prototype.modes.base import BaseRouteMode

class OnewayRandomMode(BaseRouteMode):
    label    = "거리 설정 편도 (목적지 우회)"
    mode_key = "oneway_random"
