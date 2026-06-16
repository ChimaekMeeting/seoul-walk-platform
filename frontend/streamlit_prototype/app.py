import config.path_setup  # noqa: F401 — must precede all src/ imports

import streamlit as st

from frontend.streamlit_prototype.bootstrap import create_app_context, AppContext
from frontend.streamlit_prototype.sections.page_setup import setup_page
from frontend.streamlit_prototype.sections.header import render_header


class App:

    def __init__(self):
        self._ctx: AppContext = create_app_context()

    def run(self) -> None:
        ctx = self._ctx
        setup_page(ctx.walk_route_map)

        lat, lng, env = render_header(ctx)

        config         = ctx.walk_sidebar.render()
        input_mode     = config["input_mode"]
        selected_mode  = config["selected_mode"]
        distance_km    = config["distance_km"]
        child_friendly = config["child_friendly"]
        safety_w       = config["safety_w"]
        nature_w       = config["nature_w"]

        ctx.weather_card.render(env)

        if input_mode == "AI 챗봇":
            updated = ctx.chat_panel.render(selected_mode, distance_km, safety_w, nature_w)
            if updated:
                safety_w, nature_w, selected_mode, distance_km = updated

        ctx.walk_route_map.init_session_state()
        ctx.walk_route_map.render(input_mode)
        ctx.coordinate_panel.render()

        if st.session_state.get("route_result"):
            ctx.walk_result_panel.render(st.session_state.route_result)

        ctx.walk_route_button.render(
            input_mode, selected_mode, distance_km, child_friendly, safety_w, nature_w, lat, lng
        )


if __name__ == "__main__":
    App().run()
