import streamlit as st

from src.database.postgresql import health_check
from src.service.route.route_flat import get_flat_mode_options


class RouteSidebar:

    def render(self) -> dict:
        """
        DB 상태, 입력 방식, 경로 모드·거리·가중치 슬라이더를 렌더링하고 설정값 딕셔너리를 반환합니다.
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
            label                  = st.sidebar.selectbox("경로 모드", options=list(mode_options.keys()), key="route_mode_select")
            config["selected_mode"] = mode_options[label]
            config["distance_km"]   = st.sidebar.slider("목표 거리 (km)", 1.0, 10.0, 3.0, 0.5, key="distance_km")
            config["safety_w"]      = st.sidebar.slider("안전 가중치", 0.1, 3.0, 1.0, 0.1, key="safety_w")
            config["nature_w"]      = st.sidebar.slider("자연 가중치", 0.1, 3.0, 1.0, 0.1, key="nature_w")
            config["slope_w"]       = st.sidebar.slider("경사 회피 (평지 선호)", 0.1, 2.0, 1.0, 0.1, key="slope_w")
        else:
            config["selected_mode"] = "circular"
            config["distance_km"]   = 3.0
            config["safety_w"]      = 0.5
            config["nature_w"]      = 0.5
            config["slope_w"]       = 1.0

        return config
