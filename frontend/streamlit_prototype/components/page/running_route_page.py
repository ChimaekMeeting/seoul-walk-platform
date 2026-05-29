import streamlit as st
from dotenv import load_dotenv
from streamlit_folium import st_folium

from frontend.streamlit_prototype.components.sidebar.running_route_sidebar import RunningRouteSidebar
from frontend.streamlit_prototype.components.map.running_route_map import RunningRouteMap
from frontend.streamlit_prototype.components.panel.running_route_panel import RunningRoutePanel

load_dotenv()


class RunningRoutePage:

    SEOUL_CENTER = [37.5665, 126.9780]

    def __init__(self):
        self.sidebar   = RunningRouteSidebar()
        self.route_map = RunningRouteMap()
        self.running_route_panel   = RunningRoutePanel()

    def _init_session_state(self):
        """
        Streamlit 세션 상태 키가 없을 경우 기본값으로 초기화합니다.
        """
        for key, default in [("start", None), ("end", None), ("click_mode", "start"), ("result", None)]:
            if key not in st.session_state:
                st.session_state[key] = default

    def run(self):
        """
        런닝/다이어트 경로 추천 페이지 전체를 순서대로 렌더링합니다.
        """
        st.set_page_config(page_title="런닝/다이어트 경로 테스트", page_icon="🏃", layout="wide")
        st.title("🏃 런닝/다이어트 경로 테스트")
        st.caption("지도를 클릭해 출발지·도착지를 설정하고 경로를 추천받으세요.")

        self._init_session_state()
        self.sidebar.render()

        center   = st.session_state.start or self.SEOUL_CENTER
        m        = self.route_map.build(center)
        map_data = st_folium(m, width="100%", height=520, returned_objects=["last_clicked"])

        if map_data and map_data.get("last_clicked"):
            clicked = [map_data["last_clicked"]["lat"], map_data["last_clicked"]["lng"]]
            if st.session_state.click_mode == "start" and clicked != st.session_state.start:
                st.session_state.start = clicked
                st.session_state.result = None
                st.rerun()
            elif st.session_state.click_mode == "end" and clicked != st.session_state.end:
                st.session_state.end = clicked
                st.session_state.result = None
                st.rerun()

        if st.session_state.result:
            self.running_route_panel.render(st.session_state.result)
