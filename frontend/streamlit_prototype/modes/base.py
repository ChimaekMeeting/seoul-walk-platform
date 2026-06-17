"""
frontend/streamlit_prototype/modes/base.py

경로 모드 플러그인 구조의 기반 클래스 및 데이터 모델 정의

RouteParams dataclass와 BaseRouteMode ABC를 포함
새 경로 모드 추가 시 BaseRouteMode를 상속하고 modes/registry.py에 등록
ABC : ABstract Class (추상 클래스)
"""
import streamlit as st
from abc import ABC
from dataclasses import dataclass
from typing import ClassVar


@dataclass
class RouteParams:
    """
    경로 계산에 필요한 파라미터를 담는 dataclass
    mode_key, distance_km, child_friendly, safety_w, nature_w를 포함
    """ 
    mode_key:       str
    distance_km:    float
    child_friendly: bool
    safety_w:       float
    nature_w:       float


class BaseRouteMode(ABC):
    """
    모든 경로 모드의 기반 ABC
    서브클래스는 label과 mode_key(ClassVar) 정의 필수
    """ 
    label:    ClassVar[str]
    mode_key: ClassVar[str]

    def default_params(self) -> RouteParams:
        """
        input : X
        output: RouteParams

        해당 모드의 기본 RouteParams를 반환
        """
        return RouteParams(
            mode_key       = self.mode_key,
            distance_km    = 3.0,
            child_friendly = False,
            safety_w       = 1.0,
            nature_w       = 1.0,
        )

    def render_params(self) -> RouteParams:
        """
        input : X
        output: RouteParams

        사이드바에 km 슬라이더 UI를 렌더링하고 사용자 입력 기반 RouteParams를 반환
        UI가 필요 없는 모드는 서브클래스에서 오버라이드하여 default_params()를 반환
        """
        d = self.default_params()
        return RouteParams(
            mode_key       = self.mode_key,
            distance_km    = st.sidebar.slider("목표 거리 (km)", 1.0, 10.0, d.distance_km, 0.5, key="distance_km"),
            child_friendly = d.child_friendly,
            safety_w       = d.safety_w,
            nature_w       = d.nature_w,
        )

