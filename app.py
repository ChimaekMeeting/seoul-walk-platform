import os
from pathlib import Path

# 환경 변수
from dotenv import load_dotenv

# Streamlit
import streamlit as st
from streamlit_folium import st_folium

# 지도
import folium

# DB / 서비스
from src.database.postgresql import health_check
from src.client.weather import get_environment_info
from src.service.route_service import get_route


load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

MAPBOX_TOKEN = os.getenv("MAPBOX_API_KEY")
print("TOKEN:", MAPBOX_TOKEN)
SEOUL_CENTER = [37.5665, 126.9780]

st.set_page_config(page_title="서울 산책 플랫폼", page_icon="🚶", layout="wide")
st.title("🚶 서울시 산책 경로 추천")
st.markdown("---")

db_ok = health_check()
st.sidebar.markdown("### 시스템 상태")

if db_ok:
    st.sidebar.success("🟢 DB 연결됨")
else:
    st.sidebar.error("🔴 DB 연결 실패")

# 실제 API 데이터 가져오기
env = get_environment_info()

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("현재 날씨", env["weather_status"], env["weather_msg"])
with col2:
    st.metric("미세먼지", env["air_status"], env["air_msg"])
with col3:
    st.metric("추천 경로", "3개", "평균 3.2km")

# 세션 상태 초기화
if "start" not in st.session_state:
    st.session_state.start = None
if "end" not in st.session_state:
    st.session_state.end = None
if "mode" not in st.session_state:
    st.session_state.mode = "start"
if "route_coordinates" not in st.session_state:
    st.session_state.route_coordinates = None
if "route_distance" not in st.session_state:
    st.session_state.route_distance = None

mode = st.radio(
    "설정 모드",
    options=["start", "end"],
    format_func=lambda x: "출발지 설정" if x == "start" else "도착지 설정",
    horizontal=True,
    key="mode"
)

label = "출발지" if st.session_state.mode == "start" else "도착지"
st.info(f"📍 **{label}** 설정 중 — 지도를 클릭하세요")


# 지도 생성
m = folium.Map(
    location=SEOUL_CENTER,
    zoom_start=13,
    tiles=(
        f"https://api.mapbox.com/styles/v1/mapbox/streets-v12/tiles/512"
        f"/{{z}}/{{x}}/{{y}}@2x?access_token={MAPBOX_TOKEN}"
    ),
    attr="Mapbox",
    zoom_offset=-1  # 512타일 쓸 때 필요
)

# 마커 추가
if st.session_state.start:
    folium.Marker(
        st.session_state.start,
        popup="출발지",
        tooltip="출발지",
        icon=folium.Icon(color="green", icon="play", prefix="fa")
    ).add_to(m)

if st.session_state.end:
    folium.Marker(
        st.session_state.end,
        popup="도착지",
        tooltip="도착지",
        icon=folium.Icon(color="red", icon="flag", prefix="fa")
    ).add_to(m)

if st.session_state.route_coordinates:
    folium.PolyLine(
        locations=st.session_state.route_coordinates,
        color="#4A90E2",
        weight=5,
        opacity=0.8,
        tooltip=f"총 {st.session_state.route_distance}km"
    ).add_to(m)
    m.fit_bounds(st.session_state.route_coordinates)

# 출발지/도착지 둘 다 있으면 지도 범위 자동 조정
if st.session_state.start and st.session_state.end:
    m.fit_bounds([st.session_state.start, st.session_state.end])

# 지도 렌더링
map_data = st_folium(m, width="100%", height=520, returned_objects=["last_clicked"])

# 클릭 이벤트 처리
if map_data and map_data.get("last_clicked"):
    lat = map_data["last_clicked"]["lat"]
    lng = map_data["last_clicked"]["lng"]
    clicked = [lat, lng]

    # 이미 같은 좌표면 rerun 안 함
    if st.session_state.mode == "start" and clicked != st.session_state.start:
        st.session_state.start = clicked
        st.rerun()
    elif st.session_state.mode == "end" and clicked != st.session_state.end:
        st.session_state.end = clicked
        st.rerun()

# 좌표 표시
st.divider()
col1, col2 = st.columns(2)
with col1:
    if st.session_state.start:
        lat, lng = st.session_state.start
        st.success(f"🟢 출발지\n\n`{lat:.5f}, {lng:.5f}`")
        if st.button("출발지 초기화"):
            st.session_state.start = None
            st.rerun()
    else:
        st.warning("출발지를 설정해주세요")

with col2:
    if st.session_state.end:
        lat, lng = st.session_state.end
        st.error(f"🔴 도착지\n\n`{lat:.5f}, {lng:.5f}`")
        if st.button("도착지 초기화"):
            st.session_state.end = None
            st.rerun()
    else:
        st.warning("도착지를 설정해주세요")


# 경로 추천 버튼
if st.session_state.start:
    st.divider()
    if st.button("🚶 경로 추천받기", type="primary", use_container_width=True):
        with st.spinner("경로를 계산하는 중..."):
            intent = {"intent": "safe", "distance_km": 3.0}  # 임시
            result = get_route(
                start_lat=st.session_state.start[0],
                start_lng=st.session_state.start[1],
                intent=intent,
                end_lat=st.session_state.end[0] if st.session_state.end else None,
                end_lng=st.session_state.end[1] if st.session_state.end else None,
            ) 
            st.session_state.route_coordinates = result["coordinates"]
            st.session_state.route_distance = result["total_distance_km"]
            st.rerun()  # 지도 다시 렌더링

st.info("팀원 분들, 담당 모듈을 작업한 후 이곳(app.py)에 조립해 주세요!")