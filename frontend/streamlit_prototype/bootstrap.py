import time
from dataclasses import dataclass

import streamlit as st

from src.repository.network.graph_repository import GraphRepository
from frontend.streamlit_prototype.components.card.weather_card import WeatherCard
from frontend.streamlit_prototype.components.carousel.banner_carousel import BannerCarousel
from frontend.streamlit_prototype.components.panel.chat_panel import ChatPanel
from frontend.streamlit_prototype.components.panel.coordinate_panel import CoordinatePanel
from frontend.streamlit_prototype.components.panel.walk_result_panel import WalkResultPanel
from frontend.streamlit_prototype.components.sidebar.walk_sidebar import WalkSidebar
from frontend.streamlit_prototype.components.map.walk_route_map import WalkRouteMap
from frontend.streamlit_prototype.components.button.walk_route_button import WalkRouteButton
from frontend.streamlit_prototype.providers.base import EnvProvider
from frontend.streamlit_prototype.providers.registry import build_provider


@st.cache_resource
def _load_graph():
    G = GraphRepository.load_graph()
    print(list(G.nodes(data=True))[:3])
    return G


@dataclass
class AppContext:
    weather_card:      WeatherCard
    banner_carousel:   BannerCarousel
    chat_panel:        ChatPanel
    coordinate_panel:  CoordinatePanel
    walk_result_panel: WalkResultPanel
    walk_sidebar:      WalkSidebar
    walk_route_map:    WalkRouteMap
    walk_route_button: WalkRouteButton
    provider:          EnvProvider


def create_app_context() -> AppContext:
    t = time.time()
    G = _load_graph()
    print(f"graph: {time.time()-t:.2f}s")

    return AppContext(
        weather_card      = WeatherCard(),
        banner_carousel   = BannerCarousel(),
        chat_panel        = ChatPanel(),
        coordinate_panel  = CoordinatePanel(),
        walk_result_panel = WalkResultPanel(),
        walk_sidebar      = WalkSidebar(),
        walk_route_map    = WalkRouteMap(G),
        walk_route_button = WalkRouteButton(G),
        provider          = build_provider(),
    )
