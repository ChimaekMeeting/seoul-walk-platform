"""
런닝/다이어트 경로 테스트 Streamlit 앱

실행 방법:
    streamlit run running_app.py
"""

import streamlit as st
import folium
from streamlit_folium import st_folium

from src.service.route.running_route_service import get_circular_route, get_oneway_route

# ──────────────────────────────────────────────
# 페이지 설정
# ──────────────────────────────────────────────

st.set_page_config(
    page_title="런닝/다이어트 경로 테스트",
    page_icon="🏃",
    layout="wide",
)

st.title("🏃 런닝/다이어트 경로 테스트")
st.caption("지도를 클릭해 출발지·도착지를 설정하고 경로를 추천받으세요.")

# ──────────────────────────────────────────────
# 세션 상태 초기화
# ──────────────────────────────────────────────

for key, default in [
    ("start", None),
    ("end", None),
    ("click_mode", "start"),
    ("result", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ──────────────────────────────────────────────
# 사이드바 — 파라미터 설정
# ──────────────────────────────────────────────

with st.sidebar:
    st.header("⚙️ 경로 설정")

    route_mode = st.radio(
        "코스 유형",
        ["순환 (출발지로 돌아오기)", "편도 — 랜덤 우회", "편도 — 최단거리"],
        key="route_mode",
    )

    target_km = st.slider("목표 거리 (km)", 1.0, 20.0, 5.0, 0.5)
    radius_m  = st.slider("DB 코스 검색 반경 (m)", 500, 15000, 5000, 500)

    st.divider()

    # 클릭 모드 토글
    is_oneway = route_mode != "순환 (출발지로 돌아오기)"
    if is_oneway:
        st.radio(
            "지도 클릭 대상",
            ["start", "end"],
            format_func=lambda x: "🟢 출발지" if x == "start" else "🔴 도착지",
            key="click_mode",
            horizontal=True,
        )
    else:
        st.session_state.click_mode = "start"
        st.info("🟢 출발지를 지도에서 클릭하세요")

    st.divider()

    # 좌표 현황
    if st.session_state.start:
        lat, lng = st.session_state.start
        st.success(f"🟢 출발지\n`{lat:.5f}, {lng:.5f}`")
        if st.button("출발지 초기화", use_container_width=True):
            st.session_state.start = None
            st.session_state.result = None
            st.rerun()
    else:
        st.warning("출발지 미설정")

    if is_oneway:
        if st.session_state.end:
            lat, lng = st.session_state.end
            st.error(f"🔴 도착지\n`{lat:.5f}, {lng:.5f}`")
            if st.button("도착지 초기화", use_container_width=True):
                st.session_state.end = None
                st.session_state.result = None
                st.rerun()
        else:
            st.warning("도착지 미설정")
    else:
        st.session_state.end = None

    st.divider()

    # 경로 추천 버튼
    can_run = st.session_state.start and (not is_oneway or st.session_state.end)
    if st.button("🏃 경로 추천받기", type="primary", use_container_width=True, disabled=not can_run):
        s_lat, s_lng = st.session_state.start
        with st.spinner("경로 계산 중..."):
            try:
                if route_mode == "순환 (출발지로 돌아오기)":
                    result = get_circular_route(
                        lat=s_lat, lng=s_lng,
                        target_km=target_km, radius_m=radius_m,
                    )
                else:
                    e_lat, e_lng = st.session_state.end
                    result = get_oneway_route(
                        start_lat=s_lat, start_lng=s_lng,
                        end_lat=e_lat,   end_lng=e_lng,
                        target_km=target_km,
                        use_random=(route_mode == "편도 — 랜덤 우회"),
                        radius_m=radius_m,
                    )
                st.session_state.result = result
                st.rerun()
            except Exception as e:
                st.error(f"오류: {e}")

# ──────────────────────────────────────────────
# 메인 — 지도
# ──────────────────────────────────────────────

SEOUL_CENTER = [37.5665, 126.9780]
center = st.session_state.start or SEOUL_CENTER

m = folium.Map(location=center, zoom_start=14, tiles="cartodbpositron")

# 출발지 마커
if st.session_state.start:
    folium.Marker(
        st.session_state.start,
        tooltip="출발지",
        icon=folium.Icon(color="green", icon="play", prefix="fa"),
    ).add_to(m)

# 도착지 마커
if st.session_state.end:
    folium.Marker(
        st.session_state.end,
        tooltip="도착지",
        icon=folium.Icon(color="red", icon="flag", prefix="fa"),
    ).add_to(m)

# 경로 폴리라인
result = st.session_state.result
if result and result.get("coordinates"):
    coords = result["coordinates"]
    folium.PolyLine(
        locations=coords,
        color="#E53935",
        weight=5,
        opacity=0.85,
        tooltip=f"총 {result['total_distance_km']} km",
    ).add_to(m)
    m.fit_bounds(coords)

# DB 추천 코스 마커 (파란 원)
if result:
    for course in result.get("matched_courses", []):
        folium.CircleMarker(
            location=[course["start_lat"], course["start_lng"]],
            radius=8,
            color="#1565C0",
            fill=True,
            fill_color="#42A5F5",
            fill_opacity=0.7,
            tooltip=f"[{course['course_type']}] {course['name']} ({course.get('distance_m', 0)/1000:.1f}km)",
        ).add_to(m)

# 지도 렌더링 & 클릭 이벤트
map_data = st_folium(m, width="100%", height=520, returned_objects=["last_clicked"])

if map_data and map_data.get("last_clicked"):
    clicked = [map_data["last_clicked"]["lat"], map_data["last_clicked"]["lng"]]
    if st.session_state.click_mode == "start" and clicked != st.session_state.start:
        st.session_state.start = clicked
        st.session_state.result = None
        st.rerun()
    elif st.session_state.click_mode == "end" and clicked != st.session_state.end:
        st.session_state.end = clicked
        st.session_state.result = None
        st.rerun()

# ──────────────────────────────────────────────
# 결과 패널
# ──────────────────────────────────────────────

if result:
    st.divider()

    if result.get("error"):
        st.error(f"⚠️ {result['error']}")
    else:
        # 경로 요약
        c1, c2, c3 = st.columns(3)
        c1.metric("총 거리", f"{result['total_distance_km']} km")
        c2.metric("모드", result.get("mode", "-"))
        avg_speed = 6.0  # 런닝 평균 속도 km/h
        time_min = round(result["total_distance_km"] / avg_speed * 60)
        c3.metric("예상 소요 시간", f"{time_min} 분")

        # DB 추천 코스 목록
        matched = result.get("matched_courses", [])
        st.markdown(f"#### 📍 반경 내 DB 추천 코스 {len(matched)}건")
        if matched:
            for course in matched:
                dist_from = course.get("distance_from_origin_m", 0)
                tags = ", ".join(course.get("tags", []))
                with st.expander(
                    f"**{course['name']}** — {course['course_type']} / "
                    f"{(course.get('distance_m') or 0)/1000:.1f}km / "
                    f"출발지까지 {dist_from/1000:.1f}km"
                ):
                    col_a, col_b = st.columns(2)
                    col_a.markdown(f"- **난이도:** {course.get('difficulty', '-')}")
                    col_a.markdown(f"- **순환여부:** {'순환' if course['is_circular'] else '편도'}")
                    col_b.markdown(f"- **태그:** `{tags}`")
                    if course.get("description"):
                        st.caption(course["description"])
        else:
            st.info("반경 내 매칭된 DB 코스가 없습니다.")
