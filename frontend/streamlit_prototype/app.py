import config.path_setup  # noqa: F401 — must precede all src/ imports

import streamlit as st

from frontend.streamlit_prototype.bootstrap import create_app_context, AppContext
from frontend.streamlit_prototype.sections.page_setup import setup_page
from frontend.streamlit_prototype.sections.header import render_header
from frontend.streamlit_prototype.sections.sidebar import render_sidebar
from frontend.streamlit_prototype.modes.base import RouteParams


class App:

    def __init__(self):
        self._ctx: AppContext = create_app_context()

    def run(self) -> None:
        ctx = self._ctx
        setup_page(ctx.walk_route_map)

        lat, lng, env  = render_header(ctx)
        sidebar        = render_sidebar()
        ctx.weather_card.render(env)

        params = sidebar.params
        if sidebar.input_mode == "AI 챗봇":
            updated = ctx.chat_panel.render(params.mode_key, params.distance_km, params.safety_w, params.nature_w)
            if updated:
                safety_w, nature_w, mode_key, distance_km = updated
                params = RouteParams(
                    mode_key=mode_key, distance_km=distance_km,
                    child_friendly=params.child_friendly,
                    safety_w=safety_w, nature_w=nature_w,
                )

        ctx.walk_route_map.init_session_state()
        ctx.walk_route_map.render(sidebar.input_mode)
        ctx.coordinate_panel.render()

        if st.session_state.get("route_result"):
            ctx.walk_result_panel.render(st.session_state.route_result)

        ctx.walk_route_button.render(
            sidebar.input_mode, params.mode_key, params.distance_km,
            params.child_friendly, params.safety_w, params.nature_w, lat, lng
        )


if __name__ == "__main__":
    App().run()
