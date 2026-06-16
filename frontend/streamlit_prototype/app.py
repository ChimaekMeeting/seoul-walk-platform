import config.path_setup  # noqa: F401 — must precede all src/ imports

from frontend.streamlit_prototype.bootstrap import create_app_context, AppContext
from frontend.streamlit_prototype.sections.page_setup import setup_page
from frontend.streamlit_prototype.sections.header import render_header
from frontend.streamlit_prototype.sections.sidebar import render_sidebar, apply_input_mode
from frontend.streamlit_prototype.sections.map_section import render_map
from frontend.streamlit_prototype.sections.result_section import render_result


class App:

    def __init__(self):
        self._ctx: AppContext = create_app_context()

    def run(self) -> None:
        ctx           = self._ctx
        setup_page(ctx.walk_route_map)
        lat, lng, env = render_header(ctx)
        sidebar       = render_sidebar()
        ctx.weather_card.render(env)
        params        = apply_input_mode(ctx, sidebar)
        render_map(ctx, sidebar)
        render_result(ctx, sidebar, params, lat, lng)


if __name__ == "__main__":
    App().run()
