import config.path_setup  # noqa: F401 — must precede all src/ imports

import time
import streamlit as st

from frontend.streamlit_prototype.bootstrap import create_app_context, AppContext
from frontend.streamlit_prototype.sections.page_setup import setup_page


class App:

    def __init__(self):
        ctx: AppContext          = create_app_context()
        self._weather_card       = ctx.weather_card
        self._banner_data        = ctx.banner_data
        self._banner_carousel    = ctx.banner_carousel
        self._chat_panel         = ctx.chat_panel
        self._coordinate_panel   = ctx.coordinate_panel
        self._walk_result_panel  = ctx.walk_result_panel
        self._walk_sidebar       = ctx.walk_sidebar
        self._walk_route_map     = ctx.walk_route_map
        self._walk_route_button  = ctx.walk_route_button

    def run(self) -> None:
        setup_page(self._walk_route_map)

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
