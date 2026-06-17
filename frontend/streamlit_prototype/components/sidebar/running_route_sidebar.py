import streamlit as st

from src.route_engine.engines.circular.running import CircularRunningEngine
from src.route_engine.engines.oneway.running import OnewayRunningEngine
from src.route_engine.schema import CircularRouteInput, OnewayRouteInput


class RunningRouteSidebar:

    def _calculate_route(self, config: dict):
        """
        설정값을 기반으로 런닝 경로를 계산하고 결과를 세션 상태에 저장합니다.
        """
        s_lat, s_lng = st.session_state.start
        with st.spinner("경로 계산 중..."):
            try:
                if not config["is_oneway"]:
                    inp    = CircularRouteInput(start_lat=s_lat, start_lon=s_lng, target_km=config["target_km"])
                    engine = CircularRunningEngine(inp)
                else:
                    e_lat, e_lng = st.session_state.end
                    inp    = OnewayRouteInput(
                        start_lat=s_lat, start_lon=s_lng,
                        end_lat=e_lat,   end_lon=e_lng,
                        target_km=config["target_km"],
                    )
                    engine = OnewayRunningEngine(inp)
                output = engine.run()
                result = {
                    "mode":              output.mode,
                    "coordinates":       output.coordinates,
                    "total_distance_km": output.total_km,
                    "matched_courses":   [c.model_dump() for c in engine.matched_courses],
                    "error":             output.fallback_reason.value if output.fallback_reason else None,
                }
                st.session_state.result = result
                st.rerun()
            except Exception as e:
                st.error(f"오류: {e}")

    def render(self) -> dict:
        """
        코스 유형, 목표 거리, 선호도 슬라이더, 좌표 표시, 경로 추천 버튼을 렌더링하고 설정값을 반환합니다.
        """
        config = {}
        with st.sidebar:
            st.header("⚙️ 경로 설정")
            route_mode = st.radio("코스 유형", ["순환 (출발지로 돌아오기)", "편도 — 랜덤 우회"], key="route_mode")

            config["target_km"]    = st.slider("목표 거리 (km)", 1.0, 20.0, 5.0, 0.5)
            config["radius_m"]     = st.slider("DB 코스 검색 반경 (m)", 500, 1500, 1000, 100)
            config["slope_weight"] = st.slider("평지 선호도", 1.0, 3.0, 1.5, 0.1)
            config["type_bonus"]   = st.slider("공원/하천 선호도", 1.0, 3.0, 2.0, 0.1)
            config["is_oneway"]    = route_mode != "순환 (출발지로 돌아오기)"

            st.divider()
            if config["is_oneway"]:
                st.radio(
                    "지도 클릭 대상", ["start", "end"],
                    format_func=lambda x: "🟢 출발지" if x == "start" else "🔴 도착지",
                    key="click_mode", horizontal=True,
                )
            else:
                st.session_state.click_mode = "start"
                st.session_state.end = None
                st.info("🟢 출발지를 지도에서 클릭하세요")

            st.divider()
            if st.session_state.start:
                lat, lng = st.session_state.start
                st.success(f"🟢 출발지\n`{lat:.5f}, {lng:.5f}`")
                if st.button("출발지 초기화", use_container_width=True):
                    st.session_state.start = None
                    st.session_state.result = None
                    st.rerun()
            else:
                st.warning("출발지 미설정")

            if config["is_oneway"]:
                if st.session_state.end:
                    lat, lng = st.session_state.end
                    st.error(f"🔴 도착지\n`{lat:.5f}, {lng:.5f}`")
                    if st.button("도착지 초기화", use_container_width=True):
                        st.session_state.end = None
                        st.session_state.result = None
                        st.rerun()
                else:
                    st.warning("도착지 미설정")

            st.divider()
            can_run = st.session_state.start and (not config["is_oneway"] or st.session_state.end)
            if st.button("🏃 경로 추천받기", type="primary", use_container_width=True, disabled=not can_run):
                self._calculate_route(config)

        return config
