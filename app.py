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
from src.service.banner_service import get_banner
from streamlit.components.v1 import html as st_html
from src.service.banner_service import (
    get_banner, get_active_event, _get_event_text, BANNERS, _is_hot, _is_humid
)
from datetime import datetime
from streamlit_modal import Modal

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
env = get_weather(lat, lng)
print(f"weather: {time.time()-t:.2f}s"); t = time.time()

# ── 배너 리스트 생성 ──────────────────────────
def get_banner_list(weather: dict) -> list:
    """
    홈 화면에 노출할 배너 목록을 반환합니다.
    이벤트 배너가 있으면 맨 앞에 추가하고,
    나머지는 날씨/시간대 기반 고정 배너로 채웁니다.
    """
    hour = datetime.now().hour
    banners = []

    # 1순위: 이벤트 배너 (있으면 맨 앞에)
    active_event = get_active_event()
    if active_event:
        banners.append(_get_event_text(active_event))

    # 2순위: 시즌 배너 (날씨 기반)
    status = weather.get("weather_status", "")
    msg    = weather.get("weather_msg", "")
    if _is_hot(msg):
        if 6 <= hour < 9:
            banners.append(BANNERS["season"]["hot_morning"])
        elif _is_humid(status):
            banners.append(BANNERS["season"]["hot_humid"])
        else:
            banners.append(BANNERS["season"]["hot_sunny"])

    # 3순위: 고정 배너 (시간대 기반 전체 추가)
    if hour < 17:
        keys = ["dog", "healing"]
    elif hour < 21:
        keys = ["dog", "healing", "night"]
    else:
        keys = ["night"]

    for key in keys:
        banners.append(BANNERS["fixed"][key])

    return banners

banners = get_banner_list(weather=env)

# ── 모달 초기화 ──
modal = Modal(key="banner_modal", title="")

# ── 세션 상태 초기화 ──
if "selected_banner" not in st.session_state:
    st.session_state.selected_banner = None

# ── 배너 캐러셀 HTML/JS ───────────────────────
banner_items = ""
dots = ""
for i, b in enumerate(banners):
    active_class = "active" if i == 0 else ""
    banner_items += f"""
    <div class="banner-item {active_class}">
        <div class="banner-label">오늘의 추천 산책</div>
        <div class="banner-text">{b['emoji']} {b['text']}</div>
        <div class="banner-sub">{b['sub']}</div>
    </div>
    """
    dots += f'<div class="dot {"active" if i == 0 else ""}" onclick="goTo({i})"></div>'

carousel_html = f"""
<div style="width:100%; margin-bottom: 20px;">
    <div class="carousel-wrap">
        <div class="carousel">
            {banner_items}
        </div>
        <div class="dots">{dots}</div>
    </div>
</div>

<style>
    .carousel-wrap {{
        background: linear-gradient(135deg, #e8f5e9 0%, #e3f2fd 100%);
        border-radius: 16px;
        border: 1px solid #c8e6c9;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        padding: 20px 24px 14px;
        position: relative;
        overflow: hidden;
    }}
    .carousel {{
        position: relative;
        min-height: 80px;
    }}
    .banner-item {{
        display: none;
        animation: fadeIn 0.5s ease;
    }}
    .banner-item.active {{
        display: block;
    }}
    @keyframes fadeIn {{
        from {{ opacity: 0; transform: translateY(6px); }}
        to   {{ opacity: 1; transform: translateY(0); }}
    }}
    .banner-label {{
        font-size: 12px;
        color: #888;
        margin-bottom: 6px;
    }}
    .banner-text {{
        font-size: 20px;
        font-weight: 700;
        color: #1b5e20;
        margin-bottom: 4px;
    }}
    .banner-sub {{
        font-size: 14px;
        color: #555;
    }}
    .dots {{
        display: flex;
        justify-content: center;
        gap: 6px;
        margin-top: 14px;
    }}
    .dot {{
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: #c8e6c9;
        cursor: pointer;
        transition: background 0.3s;
    }}
    .dot.active {{
        background: #2e7d32;
    }}
</style>

<script>
    const items = document.querySelectorAll('.banner-item');
    const dots  = document.querySelectorAll('.dot');
    let current = 0;
    let timer;

    function goTo(index) {{
        items[current].classList.remove('active');
        dots[current].classList.remove('active');
        current = index;
        items[current].classList.add('active');
        dots[current].classList.add('active');
        resetTimer();
    }}

    function next() {{
        goTo((current + 1) % items.length);
    }}

    function resetTimer() {{
        clearInterval(timer);
        timer = setInterval(next, 3500); // 3.5초마다 자동 넘김
    }}

    resetTimer();
</script>
"""

st_html(carousel_html, height=160)

# ── 배너 선택 버튼 ──
cols = st.columns(len(banners))
for i, (col, banner) in enumerate(zip(cols, banners)):
    with col:
        if st.button(f"{banner['emoji']}", key=f"banner_btn_{i}"):
            st.session_state.selected_banner = banner
            modal.open()

# ── 모달 팝업 내용 ──
if modal.is_open():
    with modal.container():
        b = st.session_state.selected_banner
        if b:
            st.markdown(f"### {b['emoji']} {b['text']}")
            st.markdown(f"{b['sub']}")
            st.divider()

            # 마라톤 배너일 때
            if b.get("is_event"):
                st.markdown(f"📅 **날짜:** {b['date']}")
                st.markdown(f"📍 **장소:** {b['location']}")
                if b.get("url"):
                    st.link_button("상세 정보 보기", b["url"])
                if st.button("🏃 마라톤 코스 체험하기"):
                    modal.close()
                    # 추후 코스 생성 연동
            else:
                # 일반 배너일 때
                if st.button("🗺️ 코스 추천받기"):
                    modal.close()
                    # 추후 챗봇 연동


# DB 상태
t3 = time.time()
db_ok = health_check()
print(f"health_check: {time.time()-t3:.2f}s")
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