import time
from dotenv import load_dotenv
import streamlit as st
from streamlit_folium import st_folium
from streamlit.components.v1 import html

from src.repository.network.graph_repository import GraphRepository

from frontend.streamlit_prototype.components.card.weather_card import WeatherCard
from frontend.streamlit_prototype.components.carousel.banner_data_carousel import BannerDataCarousel
from frontend.streamlit_prototype.components.carousel.banner_carousel import BannerCarousel
from frontend.streamlit_prototype.components.panel.chat_panel import ChatPanel
from frontend.streamlit_prototype.components.panel.coordinate_panel import CoordinatePanel
from frontend.streamlit_prototype.components.panel.walk_result_panel import WalkResultPanel
from frontend.streamlit_prototype.components.sidebar.walk_sidebar import WalkSidebar
from frontend.streamlit_prototype.components.map.walk_route_map import WalkRouteMap
from frontend.streamlit_prototype.components.button.walk_route_button import WalkRouteButton

load_dotenv()

SEOUL_CENTER = [37.5665, 126.9780]

t = time.time()


@st.cache_resource
def get_graph():
    G = GraphRepository.load_graph()
    print(list(G.nodes(data=True))[:3])
    return G


G = get_graph()
print(f"graph: {time.time()-t:.2f}s"); t = time.time()

_weather_card      = WeatherCard()
_banner_data       = BannerDataCarousel()
_banner_carousel   = BannerCarousel()
_chat_panel        = ChatPanel()
_coordinate_panel  = CoordinatePanel()
_walk_result_panel = WalkResultPanel()
_walk_sidebar      = WalkSidebar()
_walk_route_map    = WalkRouteMap(G)
_walk_route_button = WalkRouteButton(G)

st.set_page_config(page_title="서울 산책 플랫폼", page_icon="🚶", layout="wide")
st.title("🚶 서울시 산책 경로 추천")
st.markdown("---")

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
        function(err) { console.log("위치 권한 거부:", err); }
    );
    </script>
    """,
    height=0,
)
print(f"html gps: {time.time()-t:.2f}s"); t = time.time()

params = st.query_params
lat = float(params.get("lat", 37.5665))
lng = float(params.get("lng", 126.9780))

env     = _weather_card.fetch(lat, lng)
banners = _banner_data.get_banner_list(env)
_banner_carousel.render(banners)
print(f"weather+banner: {time.time()-t:.2f}s"); t = time.time()

config        = _walk_sidebar.render()
input_mode    = config["input_mode"]
selected_mode = config["selected_mode"]
distance_km   = config["distance_km"]
child_friendly = config["child_friendly"]
safety_w      = config["safety_w"]
nature_w      = config["nature_w"]

_weather_card.render(env)

if input_mode == "AI 챗봇":
    updated = _chat_panel.render(selected_mode, distance_km, safety_w, nature_w)
    if updated:
        safety_w, nature_w, selected_mode, distance_km = updated

for key, val in {
    "start": None, "end": None, "mode": "start",
    "route_coordinates": None, "route_distance": None, "route_result": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = val

if input_mode == "직접 설정":
    st.radio(
        "설정 모드",
        options=["start", "end"],
        format_func=lambda x: "출발지 설정" if x == "start" else "도착지 설정",
        horizontal=True,
        key="mode",
    )
    label = "출발지" if st.session_state.mode == "start" else "도착지"
    st.info(f"📍 **{label}** 설정 중 — 지도를 클릭하세요")

center   = st.session_state.start if st.session_state.start else SEOUL_CENTER
m        = _walk_route_map.build(center)
map_data = st_folium(m, width="100%", height=500, returned_objects=["last_clicked"])
print(f"st_folium: {time.time()-t:.2f}s"); t = time.time()

if map_data and map_data.get("last_clicked"):
    clicked = [map_data["last_clicked"]["lat"], map_data["last_clicked"]["lng"]]
    if st.session_state.mode == "start" and clicked != st.session_state.start:
        st.session_state.start = clicked
        st.rerun()
    elif st.session_state.mode == "end" and clicked != st.session_state.end:
        st.session_state.end = clicked
        st.rerun()

_coordinate_panel.render()

if st.session_state.get("route_result"):
    _walk_result_panel.render(st.session_state.route_result)

_walk_route_button.render(
    input_mode, selected_mode, distance_km, child_friendly, safety_w, nature_w, lat, lng
)
