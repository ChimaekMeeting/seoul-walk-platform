"""
frontend/streamlit_prototype/modes/circular.py

순환 산책 모드 구현체
출발지에서 출발해 동일 지점으로 돌아오는 루프 경로를 생성
render_params()는 BaseRouteMode 기본 구현(km 슬라이더)을 사용
"""
from frontend.streamlit_prototype.modes.base import BaseRouteMode

class CircularMode(BaseRouteMode):
    label    = "순환 산책 (제자리 돌아오기)"
    mode_key = "circular_random"
    needs_destination = False
