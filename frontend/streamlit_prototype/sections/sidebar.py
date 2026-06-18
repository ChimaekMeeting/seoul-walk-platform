"""
frontend/streamlit_prototype/sections/sidebar.py

경로 모드 선택 및 파라미터 입력 UI를 제공하는 사이드바 섹션
DB 연결 상태 표시, 입력 방식(직접 설정 / AI 챗봇) 선택, 선택된 모드의 파라미터 렌더링을 담당
"""

import streamlit as st
from dataclasses import dataclass

from frontend.streamlit_prototype.api.health_router import HealthRouter
from frontend.streamlit_prototype.modes.base import BaseRouteMode, RouteParams
from frontend.streamlit_prototype.modes.registry import ROUTE_MODES


@dataclass
class SidebarConfig:
    # 사이드바 입력 결과를 담는 dataclass. input_mode, mode, params를 포함
    input_mode: str
    mode:       BaseRouteMode
    params:     RouteParams


def _select_mode() -> BaseRouteMode:
    """
    input : X
    output: BaseRouteMode
    
    사이드바 selectbox에서 경로 모드를 선택하고 해당 BaseRouteMode 인스턴스를 반환
    """
    label_to_mode = {m.label: m for m in ROUTE_MODES}
    label = st.sidebar.selectbox("경로 모드", options=list(label_to_mode.keys()), key="route_mode_select")
    return label_to_mode[label]


def _render_params(mode: BaseRouteMode) -> RouteParams:
    """
    input : mode (BaseRouteMode)
    output: RouteParams

    선택된 모드의 render_params()를 호출하여 사이드바 UI를 렌더링하고 RouteParams를 반환
    """
    return mode.render_params()


def render_sidebar() -> SidebarConfig:
    """
    input : X
    output: SidebarConfig

    DB 연결 상태, 입력 방식, 모드 선택, 파라미터 입력 UI를 렌더링
    """
    db_ok = HealthRouter().get_health()
    st.sidebar.markdown("### 시스템 상태")
    st.sidebar.success("🟢 DB 연결됨") if db_ok else st.sidebar.error("🔴 DB 연결 실패")
    st.sidebar.markdown("### 경로 설정")

    input_mode = st.sidebar.radio("입력 방식", ["직접 설정", "AI 챗봇"])

    if input_mode == "직접 설정":
        mode   = _select_mode()
        params = _render_params(mode)
    else:
        mode   = ROUTE_MODES[0]
        params = mode.default_params()

    return SidebarConfig(input_mode=input_mode, mode=mode, params=params)


def apply_input_mode(ctx, sidebar: SidebarConfig) -> RouteParams:
    """
    input : ctx (AppContext), sidebar (SidebarConfig)
    output: RouteParams

    입력 방식이 AI 챗봇인 경우 ChatPanel 결과로 RouteParams를 갱신하여 반환
    직접 설정 모드에서는 sidebar.params를 그대로 반환
    """
    params = sidebar.params
    if sidebar.input_mode != "AI 챗봇":
        return params

    updated = ctx.chat_panel.render(params.mode_key, params.target_km)
    if not updated:
        return params

    mode_key, target_km = updated
    return RouteParams(mode_key=mode_key, target_km=target_km)
