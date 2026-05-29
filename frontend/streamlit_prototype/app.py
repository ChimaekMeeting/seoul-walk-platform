import time
from dotenv import load_dotenv
import streamlit as st

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


@st.cache_resource
def _load_graph():
    G = GraphRepository.load_graph()
    print(list(G.nodes(data=True))[:3])
    return G


class App:

    def __init__(self):
        t = time.time()
        G = _load_graph()
        print(f"graph: {time.time()-t:.2f}s")

        self._weather_card      = WeatherCard()
        self._banner_data       = BannerDataCarousel()
        self._banner_carousel   = BannerCarousel()
        self._chat_panel        = ChatPanel()
        self._coordinate_panel  = CoordinatePanel()
        self._walk_result_panel = WalkResultPanel()
        self._walk_sidebar      = WalkSidebar()
        self._walk_route_map    = WalkRouteMap(G)
        self._walk_route_button = WalkRouteButton(G)

    def run(self) -> None:
        """
        서울시 산책 경로 추천 페이지 전체를 순서대로 렌더링합니다.
        """
        st.set_page_config(page_title="서울 산책 플랫폼", page_icon="🚶", layout="wide")
        st.title("🚶 서울시 산책 경로 추천")
        st.markdown("---")

        self._walk_route_map.inject_geolocation_js()

        t = time.time()
        lat, lng = self._walk_route_map.get_location()
        env      = self._weather_card.fetch(lat, lng)
        banners  = self._banner_data.get_banner_list(env)
        self._banner_carousel.render(banners)
        print(f"weather+banner: {time.time()-t:.2f}s")

        config         = self._walk_sidebar.render()
        input_mode     = config["input_mode"]
        selected_mode  = config["selected_mode"]
        distance_km    = config["distance_km"]
        child_friendly = config["child_friendly"]
        safety_w       = config["safety_w"]
        nature_w       = config["nature_w"]

        self._weather_card.render(env)

        if input_mode == "AI 챗봇":
            updated = self._chat_panel.render(selected_mode, distance_km, safety_w, nature_w)
            if updated:
                safety_w, nature_w, selected_mode, distance_km = updated

        self._walk_route_map.init_session_state()
        self._walk_route_map.render(input_mode)
        self._coordinate_panel.render()

        if st.session_state.get("route_result"):
            self._walk_result_panel.render(st.session_state.route_result)

        self._walk_route_button.render(
            input_mode, selected_mode, distance_km, child_friendly, safety_w, nature_w, lat, lng
        )


if __name__ == "__main__":
    App().run()
