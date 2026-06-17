import streamlit as st
from dotenv import load_dotenv
from streamlit.components.v1 import html as st_html
from streamlit_folium import st_folium

from src.repository.network.graph_repository import GraphRepository

from frontend.streamlit_prototype.components.carousel.banner_data_carousel import BannerDataCarousel
from frontend.streamlit_prototype.components.carousel.banner_carousel import BannerCarousel
from frontend.streamlit_prototype.components.card.weather_card import WeatherCard
from frontend.streamlit_prototype.components.panel.chat_panel import ChatPanel
from frontend.streamlit_prototype.components.panel.route_panel import RoutePanel
from frontend.streamlit_prototype.components.sidebar.route_sidebar import RouteSidebar
from frontend.streamlit_prototype.components.map.route_map import RouteMap
from frontend.streamlit_prototype.components.panel.coordinate_panel import CoordinatePanel
from frontend.streamlit_prototype.components.button.route_button import RouteButton

load_dotenv()


@st.cache_resource
def _load_graph():
    """
    전체 그래프 데이터를 로드하고 프로세스 생애 동안 캐싱합니다.
    """
    G = GraphRepository.load_graph()
    print(list(G.nodes(data=True))[:3])
    return G


class WalkRoutePage:

    SEOUL_CENTER = [37.5665, 126.9780]

    def __init__(self):
        self.G = _load_graph()

        self.banner_data      = BannerDataCarousel()
        self.banner_carousel  = BannerCarousel()
        self.weather_card     = WeatherCard()
        self.chat_panel       = ChatPanel()
        self.route_sidebar    = RouteSidebar()
        self.route_map        = RouteMap(self.G)
        self.coordinate_panel = CoordinatePanel()
        self.route_panel    = RoutePanel()
        self.route_button     = RouteButton(self.G)

    def _render_gps_script(self):
        """
        브라우저 GPS 위치를 URL 쿼리 파라미터로 설정하는 JavaScript를 삽입합니다.
        """
        st_html(
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

    def _init_session_state(self):
        """
        지도 관련 세션 상태를 초기화합니다.
        """
        for key, val in {"start": None, "end": None, "mode": "start",
                         "route_coordinates": None, "route_distance": None, "route_result": None}.items():
            if key not in st.session_state:
                st.session_state[key] = val

    def run(self):
        """
        서울시 산책 경로 추천 페이지 전체를 순서대로 렌더링합니다.
        """
        st.set_page_config(page_title="서울 산책 플랫폼", page_icon="🚶", layout="wide")
        st.title("🚶 서울시 산책 경로 추천")
        st.markdown("---")

        self._render_gps_script()

        params = st.query_params
        lat = float(params.get("lat", 37.5665))
        lng = float(params.get("lng", 126.9780))

        env     = self.weather_card.fetch(lat, lng)
        banners = self.banner_data.get_banner_list(env)
        self.banner_carousel.render(banners)

        config        = self.route_sidebar.render()
        input_mode    = config["input_mode"]
        selected_mode = config["selected_mode"]
        distance_km   = config["distance_km"]
        safety_w      = config["safety_w"]
        nature_w      = config["nature_w"]
        slope_w       = config["slope_w"]

        self.weather_card.render(env)

        if input_mode == "AI 챗봇":
            updated = self.chat_panel.render(selected_mode, distance_km, safety_w, nature_w)
            if updated:
                safety_w, nature_w, selected_mode, distance_km = updated

        self._init_session_state()

        if input_mode == "직접 설정":
            st.radio(
                "설정 모드", options=["start", "end"],
                format_func=lambda x: "출발지 설정" if x == "start" else "도착지 설정",
                horizontal=True, key="mode",
            )
            label = "출발지" if st.session_state.mode == "start" else "도착지"
            st.info(f"📍 **{label}** 설정 중 — 지도를 클릭하세요")

        center   = st.session_state.start if st.session_state.start else self.SEOUL_CENTER
        m        = self.route_map.build(center)
        map_data = st_folium(m, width="100%", height=500, returned_objects=["last_clicked"])

        if map_data and map_data.get("last_clicked"):
            clicked = [map_data["last_clicked"]["lat"], map_data["last_clicked"]["lng"]]
            if st.session_state.mode == "start" and clicked != st.session_state.start:
                st.session_state.start = clicked
                st.rerun()
            elif st.session_state.mode == "end" and clicked != st.session_state.end:
                st.session_state.end = clicked
                st.rerun()

        self.coordinate_panel.render()

        if st.session_state.get("route_result"):
            self.route_panel.render(st.session_state.route_result)

        self.route_button.render(input_mode, selected_mode, distance_km, safety_w, nature_w, slope_w, lat, lng)
