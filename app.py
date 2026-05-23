import os
from pathlib import Path
from dotenv import load_dotenv
import streamlit as st
from streamlit_folium import st_folium
import folium
import requests
from streamlit.components.v1 import html

from src.database.postgresql import health_check
from src.client.weather_client import get_environment_info
from src.service.route.route_service import get_route
from src.repository.graph_repository import load_graph
from src.service.map_service import fetch_local_db_lines_optimized, fetch_local_db_points
from src.service.banner_service import get_banner
from streamlit.components.v1 import html as st_html
from chatbot_app import init_session, chat_and_assign_weights, run_async
from src.service.banner_service import (
    get_banner, get_active_event, _get_event_text, BANNERS, _is_hot, _is_humid
)
from datetime import datetime
from streamlit_modal import Modal

import time

t = time.time()

@st.cache_resource
def get_graph():
    G = load_graph()
    print(list(G.nodes(data=True))[:3])
    return G

G = get_graph()

load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

MAPBOX_TOKEN = os.getenv("MAPBOX_API_KEY")
SEOUL_CENTER = [37.5665, 126.9780]
print(f"dotenv: {time.time()-t:.2f}s"); t = time.time()

st.set_page_config(page_title="서울 산책 플랫폼", page_icon="🚶", layout="wide")
st.title("🚶 서울시 산책 경로 추천")
st.markdown("---")

# ── 브라우저에서 GPS 위치 받아오기 ──────────
html(
    """
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
        function(err) {
            console.log("위치 권한 거부:", err);
        }
    );
    </script>
    """,
    height=0,
)
print(f"html gps: {time.time()-t:.2f}s"); t = time.time()

# URL 파라미터에서 위치 가져오기 (없으면 서울시청 기본값)
params = st.query_params
lat = float(params.get("lat", 37.5665))
lng = float(params.get("lng", 126.9780))
print(f"query_params: {time.time()-t:.2f}s"); t = time.time()

# FastAPI 호출
@st.cache_data(ttl=300)
def get_weather(lat, lng):
    try:
        res = requests.get(
            "http://localhost:8080/api/weather", params={"lat": lat, "lng": lng}, timeout=3
        )
        response_data = res.json()
        return response_data[0] if isinstance(response_data, list) else response_data
    except Exception:
        return {
            "weather_status": "알 수 없음",
            "weather_msg": "서버 연결 실패",
            "air_status": "알 수 없음",
            "air_msg": "",
        }
    
# ── [배너] get_banner_list 함수 ──────────────────
def get_banner_list(weather: dict, hour: int | None = None) -> list:
    if hour is None:
        hour = datetime.now().hour

    status = weather.get("weather_status", "")
    msg    = weather.get("weather_msg", "")
    banners = []

    # 1순위: 이벤트 배너
    active_event = get_active_event()
    if active_event:
        banners.append(_get_event_text(active_event))

    # 2순위: 시즌 배너 (날씨 기반)
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
# ─────────────────────────────────────────────────

env = get_weather(lat, lng)

env = get_weather(lat, lng)
print(f"weather: {time.time()-t:.2f}s"); t = time.time()

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

if db_ok:
    st.sidebar.success("🟢 DB 연결됨")
else:
    st.sidebar.error("🔴 DB 연결 실패")

st.sidebar.markdown("### 경로 설정")

# 경로 모드 선택 UI 추가 (selectbox 방식 선언)
input_mode = st.sidebar.radio("입력 방식", ["직접 설정", "AI 챗봇"])

mode_options = {
    "순환 산책 (제자리 돌아오기)": "circular",
    "최단 거리 편도 (목적지 직행)": "oneway_shortest",
    "거리 설정 편도 (목적지 우회)": "oneway_random"
}

if input_mode == "직접 설정":
    selected_mode_label = st.sidebar.selectbox("경로 모드", options=list(mode_options.keys()), key="route_mode_select")
    selected_mode = mode_options[selected_mode_label]
    distance_km = st.sidebar.slider("목표 거리 (km)", 1.0, 10.0, 3.0, 0.5, key="distance_km")
    safety_w = st.sidebar.slider("안전 가중치", 0.1, 3.0, 1.0, 0.1, key="safety_w")
    nature_w = st.sidebar.slider("자연 가중치", 0.1, 3.0, 1.0, 0.1, key="nature_w")
else:
    selected_mode = "circular"
    distance_km = 3.0
    safety_w = 0.5
    nature_w = 0.5

# 메인 대시보드 UI 출력
col1, col2, col3 = st.columns(3)

with col1:
    st.metric("현재 날씨", env["weather_status"], env["weather_msg"])

with col2:
    st.metric("미세먼지", env["air_status"], env["air_msg"])

with col3:
    st.metric("추천 경로", "3개", "평균 3.2km")

if input_mode == "AI 챗봇":
    st.markdown("### 🤖 AI 산책 메이트")

    if "initialized" not in st.session_state:
        with st.spinner("세션을 연결 중입니다..."):
            run_async(init_session())
            st.rerun()

    for message in st.session_state.get("messages", []):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("챗봇과 자유롭게 대화를 나눠보세요!"):
        with st.spinner("생각 중..."):
            run_async(chat_and_assign_weights(prompt))
        st.rerun()

    state = st.session_state.get("state", {})
    if state and state.get("next_node") == "end":
        st.success("📍 산책 정보 수집 완료! 아래 지도에서 출발지를 확인하고 경로를 추천받으세요.")
        weights_data = st.session_state.get("weights", {})
        safety_w = weights_data.get("safety", 0.5)
        nature_w = weights_data.get("nature", 0.5)
        with st.expander("챗봇 반환 JSON 확인"):
            st.json({"state": state, "weights": weights_data})
        user_context = state.get("user_context", {})
        if user_context:
            mode_map = {"Circular": "circular", "Destination": "oneway_shortest", "Distance": "oneway_random"}
            selected_mode = mode_map.get(user_context.get("mode", "Circular"), "circular")
            if user_context.get("distance_km"):
                distance_km = user_context["distance_km"]

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
if "route_distance" not in st.session_state:
    st.session_state.route_distance = None
if "route_result" not in st.session_state:  
    st.session_state.route_result = None    

if input_mode == "직접 설정":
    mode = st.radio(
        "설정 모드",
        options=["start", "end"],
        format_func=lambda x: "출발지 설정" if x == "start" else "도착지 설정",
        horizontal=True,
        key="mode",
    )

    label = "출발지" if st.session_state.mode == "start" else "도착지"
    st.info(f"📍 **{label}** 설정 중 — 지도를 클릭하세요")

# 지도 인스턴스 생성
center = st.session_state.start if st.session_state.start else SEOUL_CENTER

m = folium.Map(location=center, zoom_start=15, tiles="cartodbpositron")
if MAPBOX_TOKEN:
    folium.TileLayer(
        tiles=f"https://api.mapbox.com/styles/v1/mapbox/streets-v12/tiles/256/{{z}}/{{x}}/{{y}}?access_token={MAPBOX_TOKEN}",
        attr="Mapbox", name="Mapbox Streets"
    ).add_to(m)

# 마커 렌더링 추가
if st.session_state.start:
    folium.Marker(
        st.session_state.start,
        popup="출발지",
        tooltip="출발지",
        icon=folium.Icon(color="green", icon="play", prefix="fa"),
    ).add_to(m)

if st.session_state.end:
    folium.Marker(
        st.session_state.end,
        popup="도착지",
        tooltip="도착지",
        icon=folium.Icon(color="red", icon="flag", prefix="fa"),
    ).add_to(m)

# 경로 좌표 기반 PolyLine 선조 조립 및 부가 레이어 처리
if st.session_state.route_coordinates:
    folium.PolyLine(
        locations=st.session_state.route_coordinates,
        color="#4A90E2",
        weight=6,
        opacity=0.8,
        tooltip=f"총 {st.session_state.route_distance}km",
    ).add_to(m)
    m.fit_bounds(st.session_state.route_coordinates)

    # 경로 정보 세부 노드 점 맵래핑 시각화
    if st.session_state.get("route_result"):
        for node_id in st.session_state.route_result["nodes"]:
            if node_id in G.nodes:
                node_lat = G.nodes[node_id]["y"]
                node_lon = G.nodes[node_id]["x"]
                folium.CircleMarker(
                    location=[node_lat, node_lon],
                    radius=3,
                    color="red",
                    fill=True,
                    fill_color="red",
                    fill_opacity=0.8,
                    tooltip=str(node_id),
                ).add_to(m)

        # 1레이어(도보 네트워크) 및 1.5레이어(CCTV 등) 인근 영역 데이터 연동
        center_lat, center_lon = center[0], center[1]

        # 1레이어: 도보 네트워크 선 렌더링 
        df_lines = fetch_local_db_lines_optimized(center_lat, center_lon, radius_m=300)
        if not df_lines.empty:
            for _, row in df_lines.iterrows():
                flipped_path = [[coord[1], coord[0]] for coord in row["path"]]
                folium.PolyLine(
                    locations=flipped_path,
                    color="#00BFFF",
                    weight=2,
                    opacity=0.4,
                ).add_to(m)

        # 1.5레이어: CCTV 점 렌더링 
        df_cctv = fetch_local_db_points(
            center_lat, center_lon, "safety_layer", "safety_type", "cctv", radius_m=1000
        )
        if not df_cctv.empty:
            for _, row in df_cctv.iterrows():
                folium.CircleMarker(
                    location=[row["lat"], row["lon"]],
                    radius=3,
                    color="#FFD700",
                    fill=True,
                    fill_color="#FFD700",
                    fill_opacity=0.7,
                    tooltip="CCTV",
                ).add_to(m)

# 출발지/도착지 양방 매핑 시 지도 뷰포트 피팅 조절
if st.session_state.start and st.session_state.end:
    m.fit_bounds([st.session_state.start, st.session_state.end])

# 지도 컴포넌트 렌더링 및 클릭 캐치 처리
map_data = st_folium(m, width="100%", height=500, returned_objects=["last_clicked"])
print(f"st_folium: {time.time()-t:.2f}s"); t = time.time()

if map_data and map_data.get("last_clicked"):
    lat_clicked = map_data["last_clicked"]["lat"]
    lng_clicked = map_data["last_clicked"]["lng"]
    clicked = [lat_clicked, lng_clicked]

    if st.session_state.mode == "start" and clicked != st.session_state.start:
        st.session_state.start = clicked
        st.rerun()
    elif st.session_state.mode == "end" and clicked != st.session_state.end:
        st.session_state.end = clicked
        st.rerun()

# 위경도 좌표 컴포넌트 데이터 상태 확인 인터페이스
st.divider()
c1, c2 = st.columns(2)
with c1:
    if st.session_state.start:
        st.success(f"🟢 출발지\n\n`{st.session_state.start[0]:.5f}, {st.session_state.start[1]:.5f}`")
        if st.button("출발지 초기화"):
            st.session_state.start = None
            st.rerun()
    else:
        st.warning("출발지를 설정해주세요")

with c2:
    if st.session_state.end:
        st.error(f"🔴 도착지\n\n`{st.session_state.end[0]:.5f}, {st.session_state.end[1]:.5f}`")
        if st.button("도착지 초기화"):
            st.session_state.end = None
            st.rerun()
    else:
        st.warning("도착지를 설정해주세요")

# 계산 결과 통계 정보 리포트 가시화
if st.session_state.get("route_result"):
    result = st.session_state.route_result
    st.divider()
    st.success(f"✅ 경로 생성 완료! ({result['mode']})")
    st.markdown("### 📊 경로 정보")

    col_res1, col_res2, col_res3 = st.columns(3)
    with col_res1:
        st.metric("총 거리", f"{result['total_distance_km']} km")
    with col_res2:
        mode_label = "순환 🔄" if result["mode"] in ["circular", "random_walk"] else "편도 ➡️"
        st.metric("이동 방식", mode_label)
    with col_res3:
        avg_speed = 4.0  # 도보 평균 속도 km/h
        time_min = round(result["total_distance_km"] / avg_speed * 60)
        st.metric("예상 소요 시간", f"{time_min} 분")

    st.markdown(f"**총 노드 수:** {len(result['nodes'])}개")
    st.markdown(f"**알고리즘:** {result['mode']}")

    with st.expander("📍 경로 좌표 상세보기"):
        for i, (lat_val, lng_val) in enumerate(result["coordinates"]):
            st.text(f"{i+1}. lat: {lat_val:.5f}, lng: {lng_val:.5f}")

# 경로 추천 버튼
if input_mode == "직접 설정" and st.session_state.start:
    st.divider()
    if st.button("🚶 경로 추천받기", type="primary", use_container_width=True):
        if selected_mode in ["oneway_shortest", "oneway_random"] and not st.session_state.end:
            st.error("편도 모드에서는 도착지를 설정해야 합니다!")
        else:
            with st.spinner("최적의 경로를 계산하는 중..."):
                context = {
                    "mode": selected_mode,
                    "distance_km": distance_km,
                    "origin": {
                        "place_name": "",
                        "address": "",
                        "coordinate": {
                            "lat": st.session_state.start[0],
                            "lon": st.session_state.start[1],
                        },
                    },
                    "destination": (
                        {
                            "place_name": "",
                            "address": "",
                            "coordinate": {
                                "lat": st.session_state.end[0],
                                "lon": st.session_state.end[1],
                            },
                        }
                        if st.session_state.end
                        else None
                    ),
                    "purpose": "산책",
                }
                weights = {"safety": safety_w, "nature": nature_w}
                result = get_route(context, weights, G)
                if "error" in result:
                    st.error(f"오류 발생: {result['error']}")
                else:
                    st.session_state.route_coordinates = result["coordinates"]
                    st.session_state.route_distance = result["total_distance_km"]
                    st.session_state.route_result = result
                    st.rerun()
elif input_mode == "AI 챗봇":
    state = st.session_state.get("state", {})
    if state and state.get("next_node") == "end" and not st.session_state.route_coordinates:
        user_context = state.get("user_context", {})
        origin = user_context.get("origin", {})
        destination = user_context.get("destination")
        with st.spinner("최적의 경로를 계산하는 중..."):
            context = {
                "mode": selected_mode,
                "distance_km": distance_km,
                "origin": {
                    "place_name": origin.get("place_name", ""),
                    "address": origin.get("address", ""),
                    "coordinate": {
                        "lat": origin.get("lat", lat),
                        "lon": origin.get("lon", lng),
                    },
                },
                "destination": {
                    "place_name": destination.get("place_name", ""),
                    "address": destination.get("address", ""),
                    "coordinate": {
                        "lat": destination.get("lat"),
                        "lon": destination.get("lon"),
                    },
                } if destination else None,
                "purpose": user_context.get("purpose", "산책"),
            }
            weights = {"safety": safety_w, "nature": nature_w}
            result = get_route(context, weights, G)
            if "error" in result:
                st.error(f"오류 발생: {result['error']}")
            else:
                st.session_state.route_coordinates = result["coordinates"]
                st.session_state.route_distance = result["total_distance_km"]
                st.session_state.route_result = result
                st.rerun()