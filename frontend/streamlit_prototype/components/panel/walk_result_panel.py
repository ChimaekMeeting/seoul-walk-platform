import streamlit as st

from frontend.streamlit_prototype.schema.walk_schema import (
    CircularMode,
    WalkRouteResponse,
    WalkRouteStatus,
)


class WalkResultPanel:

    def render(self, result: dict):
        """경로 결과 요약 패널을 렌더링합니다."""
        response   = WalkRouteResponse(**result)
        mode_label = "순환 🔄" if response.mode in CircularMode else "편도 ➡️"
        time_min   = round(response.total_km / 4.0 * 60)

        st.divider()
        if response.status != WalkRouteStatus.SUCCESS:
            st.error(f"경로 생성 실패: {response.status.value}")
            return

        st.success(f"✅ 경로 생성 완료! ({response.mode})")
        st.markdown("### 📊 경로 정보")

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("총 거리", f"{response.total_km} km")
        with col2:
            st.metric("이동 방식", mode_label)
        with col3:
            st.metric("예상 소요 시간", f"{time_min} 분")

        st.markdown(f"**총 노드 수:** {len(response.coordinates)}개")
        st.markdown(f"**알고리즘:** {response.mode}")
