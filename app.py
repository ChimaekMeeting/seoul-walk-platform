import os
from pathlib import Path
from dotenv import load_dotenv
import streamlit as st
from streamlit_folium import st_folium
import folium
import requests
from streamlit.components.v1 import html

from src.database.postgresql import health_check
from src.service.route.route_service import get_route
from src.repository.graph_repository import load_graph
from src.service.map_service import fetch_local_db_lines_optimized, fetch_local_db_points

import time

# ── 데이터 로드 및 초기화 ──────────────────
t = time.time()

@st.cache_resource
def get_graph():
    G = load_graph()
    return G

G = get_graph()
load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)
MAPBOX_TOKEN = os.getenv("MAPBOX_API_KEY")
SEOUL_CENTER = [37.5665, 126.9780]

st.set_page_config(page_title="서울 산책 플랫폼", page_icon="🚶", layout="wide")
st.title("🚶 서울시 산책 경로 추천")
st.markdown("---")

# ── 브라우저 GPS 위치 받아오기 ──────────
html("""
<script>
navigator.geolocation.getCurrentPosition(
    function(pos) {
        const lat = pos.coords.latitude;
        const lng = pos.coords.longitude;
        const url = new URL(window.parent.location.href);
        if (!url.searchParams.get("lat")) {
            url.searchParams.set("lat", lat);
            url.searchParams.set("lng", lng);
            window.parent.location.href = url.toString();
        }
    },
    function(err) { console.log("위치 권한 거부:", err); }
);
</script>
""", height=0)

params = st.query_params
lat = float(params.get("lat", 37.5665))
lng = float(params.get("lng", 126.9780))

# ── 사이드바: 설정 ──────────────────────
st.sidebar.markdown("### 시스템 상태")
if health_check():
    st.sidebar.success("🟢 DB 연결됨")
else:
    st.sidebar.error("🔴 DB 연결 실패")

st.sidebar.markdown("### 경로 설정")

# [변경 포인트 1] 모드 선택 UI 추가
mode_options = {
    "순환 산책 (제자리 돌아오기)": "circular",
    "최단 거리 편도 (목적지 직행)": "oneway_shortest",
    "거리 설정 편도 (목적지 우회)": "oneway_random"
}
selected_mode_label = st.sidebar.selectbox("경로 모드", options=list(mode_options.keys()))
selected_mode = mode_options[selected_mode_label]

distance_km = st.sidebar.slider("목표 거리 (km)", 1.0, 10.0, 3.0, 0.5)
safety_w = st.sidebar.slider("안전 가중치", 0.1, 3.0, 1.0, 0.1)
nature_w = st.sidebar.slider("자연 가중치", 0.1, 3.0, 1.0, 0.1)
purpose = st.sidebar.text_input("산책 목적", value="산책")

# ── 세션 상태 관리 ──────────────────────
if "start" not in st.session_state: st.session_state.start = None
if "end" not in st.session_state: st.session_state.end = None
if "mode" not in st.session_state: st.session_state.mode = "start"
if "route_result" not in st.session_state: st.session_state.route_result = None

# ── 지도 UI 및 인터랙션 ──────────────────
col_m1, col_m2 = st.columns([4, 1])
with col_m1:
    mode_radio = st.radio("위치 설정:", ["출발지 설정", "도착지 설정"], horizontal=True)
    st.session_state.mode = "start" if mode_radio == "출발지 설정" else "end"

center = st.session_state.start if st.session_state.start else SEOUL_CENTER
m = folium.Map(location=center, zoom_start=15, tiles="cartodbpositron") # 기본 타일 사용 (Mapbox 토큰 없을 시 대비)
if MAPBOX_TOKEN:
    folium.TileLayer(
        tiles=f"https://api.mapbox.com/styles/v1/mapbox/streets-v12/tiles/256/{{z}}/{{x}}/{{y}}?access_token={MAPBOX_TOKEN}",
        attr="Mapbox", name="Mapbox Streets"
    ).add_to(m)

# 마커 및 경로 그리기
if st.session_state.start:
    folium.Marker(st.session_state.start, popup="출발지", icon=folium.Icon(color="green", icon="play")).add_to(m)
if st.session_state.end:
    folium.Marker(st.session_state.end, popup="도착지", icon=folium.Icon(color="red", icon="flag")).add_to(m)

if st.session_state.route_result:
    res = st.session_state.route_result
    folium.PolyLine(locations=res["coordinates"], color="#4A90E2", weight=6, opacity=0.8).add_to(m)
    m.fit_bounds(res["coordinates"])

map_data = st_folium(m, width="100%", height=500, returned_objects=["last_clicked"])

# 클릭 시 좌표 저장
if map_data and map_data.get("last_clicked"):
    clicked = [map_data["last_clicked"]["lat"], map_data["last_clicked"]["lng"]]
    if st.session_state.mode == "start" and clicked != st.session_state.start:
        st.session_state.start = clicked
        st.rerun()
    elif st.session_state.mode == "end" and clicked != st.session_state.end:
        st.session_state.end = clicked
        st.rerun()

# ── 정보 표시 및 실행 ────────────────────
st.divider()
c1, c2 = st.columns(2)
with c1:
    st.write(f"🟢 출발지: {st.session_state.start if st.session_state.start else '미설정'}")
    if st.button("출발지 초기화"): st.session_state.start = None; st.rerun()
with c2:
    st.write(f"🔴 도착지: {st.session_state.end if st.session_state.end else '미설정'}")
    if st.button("도착지 초기화"): st.session_state.end = None; st.rerun()

# [변경 포인트 2] 경로 추천 버튼 및 Context 전달
if st.button("🚶 경로 추천받기", type="primary", use_container_width=True):
    if not st.session_state.start:
        st.error("출발지를 설정해주세요!")
    elif selected_mode in ["oneway_shortest", "oneway_random"] and not st.session_state.end:
        st.error("편도 모드에서는 도착지를 설정해야 합니다!")
    else:
        with st.spinner("최적의 경로를 계산하는 중..."):
            # 백엔드 규격에 맞게 context 구성
            context = {
                "mode": selected_mode,  # 신규 모드 전달
                "distance_km": distance_km,
                "origin": {
                    "coordinate": {"lat": st.session_state.start[0], "lon": st.session_state.start[1]}
                },
                "destination": {
                    "coordinate": {"lat": st.session_state.end[0], "lon": st.session_state.end[1]}
                } if st.session_state.end else None
            }
            weights = {"safety": safety_w, "nature": nature_w}
            
            # 서비스 호출
            result = get_route(context, weights, G)
            
            if "error" in result:
                st.error(f"오류 발생: {result['error']}")
            else:
                st.session_state.route_result = result
                st.rerun()

# 결과 리포트
if st.session_state.route_result:
    res = st.session_state.route_result
    st.success(f"✅ 경로 생성 완료! ({res['mode']})")
    col_res1, col_res2, col_res3 = st.columns(3)
    col_res1.metric("총 거리", f"{res['total_distance_km']} km")
    col_res2.metric("노드 수", f"{len(res['nodes'])} 개")
    col_res3.metric("예상 시간", f"{int(res['total_distance_km']/4*60)} 분")