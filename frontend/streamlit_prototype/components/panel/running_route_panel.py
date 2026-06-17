import streamlit as st


class RunningRoutePanel:

    def render(self, result: dict):
        """
        런닝 경로 결과 요약 지표와 DB 추천 코스 목록을 렌더링합니다.
        """
        st.divider()
        if result.get("error"):
            st.error(f"⚠️ {result['error']}")
            return

        c1, c2, c3 = st.columns(3)
        c1.metric("총 거리", f"{result['total_distance_km']} km")
        c2.metric("모드", result.get("mode", "-"))
        c3.metric("예상 소요 시간", f"{round(result['total_distance_km'] / 6.0 * 60)} 분")

        matched = result.get("matched_courses", [])
        st.markdown(f"#### 📍 반경 내 DB 추천 코스 {len(matched)}건")
        if matched:
            for course in matched:
                dist_from = course.get("distance_from_origin_m", 0)
                tags      = ", ".join(course.get("tags", []))
                with st.expander(
                    f"**{course['name']}** — {course['course_type']} / "
                    f"{(course.get('distance_m') or 0) / 1000:.1f}km / 출발지까지 {dist_from / 1000:.1f}km"
                ):
                    col_a, col_b = st.columns(2)
                    col_a.markdown(f"- **난이도:** {course.get('difficulty', '-')}")
                    col_a.markdown(f"- **순환여부:** {'순환' if course.get('is_circular', False) else '편도'}")
                    col_b.markdown(f"- **태그:** `{tags}`")
                    if course.get("description"):
                        st.caption(course["description"])
        else:
            st.info("반경 내 매칭된 DB 코스가 없습니다.")
