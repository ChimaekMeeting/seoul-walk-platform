"""
frontend/streamlit_prototype/app.py

Streamlit 앱의 진입점.

App 클래스를 통해 각 섹션(page_setup, header, sidebar, map, result)을 순서대로 렌더링한다. 
AppContext는 __init__에서 1회 생성 후 run()에서 공유된다.
"""

import config.path_setup  # noqa: F401 — must precede all src/ imports

from frontend.streamlit_prototype.bootstrap import create_app_context, AppContext
from frontend.streamlit_prototype.sections.page_setup import setup_page
from frontend.streamlit_prototype.sections.auth import require_login
from frontend.streamlit_prototype.sections.header import render_header
from frontend.streamlit_prototype.sections.sidebar import render_sidebar, apply_input_mode
from frontend.streamlit_prototype.sections.map_section import render_map
from frontend.streamlit_prototype.sections.result_section import render_result
from frontend.streamlit_prototype.sections.survey import require_survey

class App:    
    def __init__(self):
        # AppContext를 생성해 컴포넌트 초기화
        self._ctx: AppContext = create_app_context()

    def run(self) -> None:
        # 앱의 전체 렌더링 흐름을 섹션 순서대로 실행
        ctx = self._ctx
        setup_page(ctx.walk_route_map)

        # 로그인 게이트: 미로그인 시 로그인 UI만 렌더링하고 중단
        if not require_login():
            return
        
        if not require_survey():
            return

        lat, lng, env = render_header(ctx)
        sidebar       = render_sidebar()
        ctx.weather_card.render(env)
        params        = apply_input_mode(ctx, sidebar)
        render_map(ctx, sidebar)
        render_result(ctx, sidebar, params, lat, lng)


if __name__ == "__main__":
    App().run()
