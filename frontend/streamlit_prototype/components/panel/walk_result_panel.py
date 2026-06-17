import streamlit as st


class WalkResultPanel:

    def render(self, result: dict):
        """
        경로 결과 요약, 안전·자연 지수, 아이 동반 정보를 포함한 결과 패널을 렌더링합니다.
        """
        st.divider()
        st.success(f"✅ 경로 생성 완료! ({result['mode']})")
        st.markdown("### 📊 경로 정보")

        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("총 거리", f"{result['total_distance_km']} km")
        with col2:
            mode_label = "순환 🔄" if result["mode"] in ["circular", "random_walk"] else "편도 ➡️"
            st.metric("이동 방식", mode_label)
        with col3:
            avg_speed = 4.0
            time_min = round(result["total_distance_km"] / avg_speed * 60)
            st.metric("예상 소요 시간", f"{time_min} 분")
        with col4:
            st.metric("안전 지수", f"{result.get('safety_index', '-')} / 10 점")
        with col5:
            st.metric("자연 지수", f"{result.get('nature_index', '-')} / 10 점")

        if "child_index" in result:
            st.markdown("### 👨‍👩‍👧 아이 동반 산책 정보")
            child_profile = result.get("child_profile", {})
            col_c1, col_c2, col_c3 = st.columns(3)
            with col_c1:
                st.metric("아이 동반 지수", f"{result.get('child_index', '-')} / 10 점")
            with col_c2:
                st.metric("주변 보호구역", f"{child_profile.get('nearby_protection_zone_count', 0)} 곳")
            with col_c3:
                st.metric("주변 놀이시설", f"{child_profile.get('nearby_play_facility_count', 0)} 곳")

            nearby_child_places = child_profile.get("nearby_child_places", [])
            if nearby_child_places:
                st.dataframe(nearby_child_places, use_container_width=True)
            elif child_profile.get("coordinated_child_place_count", 0) == 0:
                st.caption("KAKAO_API_KEY 또는 공공데이터 API 키가 없으면 시설 좌표 기반 평가는 제한됩니다.")

        st.markdown(f"**총 노드 수:** {len(result.get('coordinates', []))}개")
        st.markdown(f"**알고리즘:** {result['mode']}")
