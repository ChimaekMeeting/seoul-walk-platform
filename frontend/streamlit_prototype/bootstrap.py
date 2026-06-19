"""
frontend/streamlit_prototype/bootstrap.py

앱 실행에 필요한 컴포넌트를 초기화하고 AppContext에 묶어 반환하는 부트스트랩 모듈
도보 네트워크 그래프는 @st.cache_resource로 캐싱 -> 앱 재실행 시 재사용
"""

from dataclasses import dataclass

import streamlit as st

import src.interfaces.dependencies as deps
from frontend.streamlit_prototype.components.card.weather_card import WeatherCard
from frontend.streamlit_prototype.components.carousel.banner_carousel import BannerCarousel
from frontend.streamlit_prototype.components.panel.chat_panel import ChatPanel
from frontend.streamlit_prototype.components.panel.coordinate_panel import CoordinatePanel
from frontend.streamlit_prototype.components.panel.walk_result_panel import WalkResultPanel
from frontend.streamlit_prototype.components.map.walk_route_map import WalkRouteMap
from frontend.streamlit_prototype.components.button.walk_route_button import WalkRouteButton
from frontend.streamlit_prototype.providers.base import EnvProvider
from frontend.streamlit_prototype.providers.registry import build_provider


@dataclass
class AppContext:    
    # 앱 전체에서 공유되는 컴포넌트 묶음
    # create_app_context()로 생성
    weather_card:      WeatherCard
    banner_carousel:   BannerCarousel
    chat_panel:        ChatPanel
    coordinate_panel:  CoordinatePanel
    walk_result_panel: WalkResultPanel
    walk_route_map:    WalkRouteMap
    walk_route_button: WalkRouteButton
    provider:          EnvProvider


def create_app_context() -> AppContext:
    """
    input : X
    output: AppContext
    
    모든 컴포넌트를 초기화하고 AppContext 인스턴스를 반환
    그래프 로드 시간을 콘솔에 출력
    """
    return AppContext(
        weather_card      = WeatherCard(),
        banner_carousel   = BannerCarousel(),
        chat_panel        = ChatPanel(),
        coordinate_panel  = CoordinatePanel(),
        walk_result_panel = WalkResultPanel(),
        walk_route_map    = WalkRouteMap(deps.G),
        walk_route_button = WalkRouteButton(),
        provider          = build_provider(),
    )
