"""
frontend/streamlit_prototype/sections/map_section.py

지도 세션 상태 초기화, 지도 렌더링, 좌표 패널을 순서대로 렌더링하는 map 섹션
"""
from frontend.streamlit_prototype.bootstrap import AppContext
from frontend.streamlit_prototype.sections.sidebar import SidebarConfig


def render_map(ctx: AppContext, sidebar: SidebarConfig) -> None:
    """
    input : ctx (AppContext), sidebar (SidebarConfig)
    output: X

    walk_route_map의 세션 상태를 초기화하고 지도를 렌더링
    coordinate_panel을 통해 현재 출발지·도착지 좌표를 표시
    """
    ctx.walk_route_map.init_session_state()
    ctx.walk_route_map.render(sidebar.input_mode)
    ctx.coordinate_panel.render()
