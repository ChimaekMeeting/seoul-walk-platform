from frontend.streamlit_prototype.bootstrap import AppContext
from frontend.streamlit_prototype.sections.sidebar import SidebarConfig


def render_map(ctx: AppContext, sidebar: SidebarConfig) -> None:
    ctx.walk_route_map.init_session_state()
    ctx.walk_route_map.render(sidebar.input_mode)
    ctx.coordinate_panel.render()
