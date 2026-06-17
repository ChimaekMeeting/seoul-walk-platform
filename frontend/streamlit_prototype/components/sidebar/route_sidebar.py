import streamlit as st

from src.database.postgresql import health_check
from src.route_engine.engines.route_flat import get_flat_mode_options

PROFILE_OPTIONS = {
    "기본 (균형)":    "default",
    "안전 우선":       "safe",
    "자연 경관":       "scenic",
    "조용한 경로":     "quiet",
    "평지 위주":       "flat",
    "아이와 함께":     "child",
    "런닝":           "running",
}


class RouteSidebar:

    def render(self) -> dict:
        """
        DB 상태, 입력 방식, 경로 모드·거리·프로필을 렌더링하고 설정값 딕셔너리를 반환합니다.
        """
        db_ok = health_check()
        st.sidebar.markdown("### 시스템 상태")
        st.sidebar.success("🟢 DB 연결됨") if db_ok else st.sidebar.error("🔴 DB 연결 실패")

        st.sidebar.markdown("### 경로 설정")
        input_mode = st.sidebar.radio("입력 방식", ["직접 설정", "AI 챗봇"])

        mode_options = {
            "순환 산책 (제자리 돌아오기)": "circular",
            "최단 거리 편도 (목적지 직행)":  "oneway_shortest",
            "거리 설정 편도 (목적지 우회)":  "oneway_random",
            **get_flat_mode_options(),
        }

        config = {"input_mode": input_mode}

        if input_mode == "직접 설정":
            label                   = st.sidebar.selectbox("경로 모드", options=list(mode_options.keys()), key="route_mode_select")
            config["selected_mode"] = mode_options[label]
            config["distance_km"]   = st.sidebar.slider("목표 거리 (km)", 1.0, 10.0, 3.0, 0.5, key="distance_km")
            profile_label           = st.sidebar.selectbox("경로 프로필", options=list(PROFILE_OPTIONS.keys()), key="profile_name")
            config["profile_name"]  = PROFILE_OPTIONS[profile_label]
        else:
            config["selected_mode"] = "circular"
            config["distance_km"]   = 3.0
            config["profile_name"]  = "default"

        return config
