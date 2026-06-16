import streamlit as st
from dataclasses import dataclass

from src.database.postgresql import health_check
from frontend.streamlit_prototype.modes.base import BaseRouteMode, RouteParams
from frontend.streamlit_prototype.modes.registry import ROUTE_MODES
from frontend.streamlit_prototype.modes.base import RouteParams


@dataclass
class SidebarConfig:
    input_mode: str
    mode:       BaseRouteMode
    params:     RouteParams


def _select_mode() -> BaseRouteMode:
    label_to_mode = {m.label: m for m in ROUTE_MODES}
    label = st.sidebar.selectbox("경로 모드", options=list(label_to_mode.keys()), key="route_mode_select")
    return label_to_mode[label]


def _render_params(mode: BaseRouteMode) -> RouteParams:
    d = mode.default_params()
    return RouteParams(
        mode_key       = mode.mode_key,
        distance_km    = st.sidebar.slider("목표 거리 (km)", 1.0, 10.0, d.distance_km, 0.5, key="distance_km"),
        child_friendly = st.sidebar.checkbox("아이와 함께 산책", value=d.child_friendly, key="child_friendly"),
        safety_w       = st.sidebar.slider("안전 가중치", 0.1, 3.0, d.safety_w, 0.1, key="safety_w"),
        nature_w       = st.sidebar.slider("자연 가중치", 0.1, 3.0, d.nature_w, 0.1, key="nature_w"),
    )


def render_sidebar() -> SidebarConfig:
    db_ok = health_check()
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
    params = sidebar.params
    if sidebar.input_mode != "AI 챗봇":
        return params

    updated = ctx.chat_panel.render(
        params.mode_key, params.distance_km, params.safety_w, params.nature_w
    )
    if not updated:
        return params

    safety_w, nature_w, mode_key, distance_km = updated
    return RouteParams(
        mode_key       = mode_key,
        distance_km    = distance_km,
        child_friendly = params.child_friendly,
        safety_w       = safety_w,
        nature_w       = nature_w,
    )