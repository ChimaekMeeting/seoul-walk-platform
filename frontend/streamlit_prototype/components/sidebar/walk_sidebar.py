import streamlit as st

from frontend.streamlit_prototype.api.health_router import HealthRouter
from frontend.streamlit_prototype.schema.walk_schema import CircularMode, OnewayMode


class WalkSidebar:

    MODE_OPTIONS: dict[str, str] = {
        "순환 산책 (제자리 돌아오기)": CircularMode.RANDOM,
        "어린이 동반 순환 산책":       CircularMode.CHILD,
        "러닝·조깅 순환":             CircularMode.RUNNING,
        "최단 거리 편도 (목적지 직행)": OnewayMode.SHORTEST,
        "거리 설정 편도 (목적지 우회)": OnewayMode.RANDOM,
        "어린이 동반 편도":            OnewayMode.CHILD,
        "러닝·조깅 편도":             OnewayMode.RUNNING,
    }

    def render(self) -> dict:
        """사이드바를 렌더링하고 설정값 딕셔너리를 반환합니다."""
        db_ok = HealthRouter().get_health()
        st.sidebar.markdown("### 시스템 상태")
        st.sidebar.success("🟢 DB 연결됨") if db_ok else st.sidebar.error("🔴 DB 연결 실패")

        st.sidebar.markdown("### 경로 설정")
        input_mode = st.sidebar.radio("입력 방식", ["직접 설정", "AI 챗봇"])

        config = {"input_mode": input_mode}

        if input_mode == "직접 설정":
            label                   = st.sidebar.selectbox("경로 모드", options=list(self.MODE_OPTIONS.keys()), key="route_mode_select")
            config["selected_mode"] = self.MODE_OPTIONS[label]
            config["target_km"]     = st.sidebar.slider("목표 거리 (km)", 1.0, 10.0, 3.0, 0.5, key="target_km")
        else:
            config["selected_mode"] = CircularMode.RANDOM
            config["target_km"]     = 3.0

        return config
