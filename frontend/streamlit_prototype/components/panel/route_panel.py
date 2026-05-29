import streamlit as st

from src.service.route.route_flat import get_mode_label


class RoutePanel:

    def render(self, result: dict):
        """
        경로 계산 결과 요약 지표와 좌표 상세 목록을 렌더링합니다.
        """
        st.divider()
        st.success(f"✅ 경로 생성 완료! ({result['mode']})")
        st.markdown("### 📊 경로 정보")

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("총 거리", f"{result['total_distance_km']} km")
        with col2:
            st.metric("이동 방식", get_mode_label(result["mode"]))
        with col3:
            avg_speed = 4.0
            time_min = round(result["total_distance_km"] / avg_speed * 60)
            st.metric("예상 소요 시간", f"{time_min} 분")

        st.markdown(f"**총 노드 수:** {len(result['nodes'])}개")
        st.markdown(f"**알고리즘:** {result['mode']}")

        with st.expander("📍 경로 좌표 상세보기"):
            for i, (lat_val, lng_val) in enumerate(result["coordinates"]):
                st.text(f"{i + 1}. lat: {lat_val:.5f}, lng: {lng_val:.5f}")
