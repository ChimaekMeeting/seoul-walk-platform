import os
import time

import folium
import streamlit as st
from streamlit.components.v1 import html
from streamlit_folium import st_folium


_SEOUL_CENTER = [37.5665, 126.9780]

_SESSION_DEFAULTS = {
    "start": None,
    "end": None,
    "mode": "start",
    "route_coordinates": None,
    "route_distance": None,
    "route_result": None,
}


class WalkRouteMap:

    def __init__(self, G):
        self.mapbox_token = os.getenv("MAPBOX_API_KEY")
        self.G = G

    def inject_geolocation_js(self) -> None:
        """
        브라우저 GPS 위치를 URL 쿼리 파라미터로 설정하는 JavaScript를 삽입합니다.
        """
        html(
            """
            <script>
            navigator.geolocation.getCurrentPosition(
                function(pos) {
                    const lat = pos.coords.latitude;
                    const lng = pos.coords.longitude;
                    const url = new URL(window.parent.location.href);
                    if (!url.searchParams.get("lat")) {
                        url.searchParams.set("lat", lat);
                        url.searchParams.set("lng", lng);
                        window.parent.location.href = url.toString();
                    }
                },
                function(err) { console.log("위치 권한 거부:", err); }
            );
            </script>
            """,
            height=0,
        )

    def get_location(self) -> tuple[float, float]:
        """
        URL 쿼리 파라미터에서 위도·경도를 읽어 반환합니다.
        """
        params = st.query_params
        lat = float(params.get("lat", _SEOUL_CENTER[0]))
        lng = float(params.get("lng", _SEOUL_CENTER[1]))
        return lat, lng

    def init_session_state(self) -> None:
        """
        지도 관련 세션 상태 키를 기본값으로 초기화합니다.
        """
        for key, val in _SESSION_DEFAULTS.items():
            if key not in st.session_state:
                st.session_state[key] = val

    def render(self, input_mode: str, mode=None) -> None:
        """
        설정 모드 선택, 지도 렌더링, 클릭 이벤트 처리를 포함한 대화형 지도 섹션을 렌더링합니다.
        mode.needs_destination에 따라 출발지만(순환) 또는 출발지+도착지(편도) 선택 UI를 노출합니다.
        """
        needs_dest = getattr(mode, "needs_destination", True)

        if input_mode == "직접 설정":
            if needs_dest:
                st.radio(
                    "설정 모드",
                    options=["start", "end"],
                    format_func=lambda x: "출발지 설정" if x == "start" else "도착지 설정",
                    horizontal=True,
                    key="mode",
                )
            else:
                # 순환 모드: 도착지 미사용 → 출발지만 설정
                st.session_state.mode = "start"
                st.session_state.end = None
            label = "출발지" if st.session_state.mode == "start" else "도착지"
            st.info(f"📍 **{label}** 설정 중 — 지도를 클릭하세요")

        t = time.time()
        center   = st.session_state.start if st.session_state.start else _SEOUL_CENTER
        m        = self.build(center)
        map_data = st_folium(m, width="100%", height=500, returned_objects=["last_clicked"])
        print(f"st_folium: {time.time()-t:.2f}s")

        if map_data and map_data.get("last_clicked"):
            clicked = [map_data["last_clicked"]["lat"], map_data["last_clicked"]["lng"]]
            if st.session_state.mode == "start" and clicked != st.session_state.start:
                st.session_state.start = clicked
                st.rerun()
            elif st.session_state.mode == "end" and clicked != st.session_state.end:
                st.session_state.end = clicked
                st.rerun()

    def build(self, center: list) -> folium.Map:
        """
        세션 상태를 기반으로 출발/도착 마커와 경로 폴리라인이 포함된 Folium 지도를 생성합니다.
        """
        m = folium.Map(location=center, zoom_start=15, tiles="cartodbpositron")

        if self.mapbox_token:
            folium.TileLayer(
                tiles=f"https://api.mapbox.com/styles/v1/mapbox/streets-v12/tiles/256/{{z}}/{{x}}/{{y}}?access_token={self.mapbox_token}",
                attr="Mapbox", name="Mapbox Streets",
            ).add_to(m)

        # 출발지/목적지: 경로가 있으면 경로 양끝, 없으면 수동 설정한 좌표 (작은 원형 마커)
        route    = st.session_state.route_coordinates
        start_pt = route[0]  if route else st.session_state.start
        end_pt   = route[-1] if route and len(route) > 1 else st.session_state.end

        if start_pt:
            folium.CircleMarker(
                location=start_pt, radius=6, tooltip="출발지",
                color="#28a745", fill=True, fill_color="#28a745", fill_opacity=1,
            ).add_to(m)
        if end_pt:
            folium.CircleMarker(
                location=end_pt, radius=6, tooltip="도착지",
                color="#dc3545", fill=True, fill_color="#dc3545", fill_opacity=1,
            ).add_to(m)

        if st.session_state.route_coordinates:
            folium.PolyLine(
                locations=st.session_state.route_coordinates,
                color="#4A90E2", weight=6, opacity=0.8,
                tooltip=f"총 {st.session_state.route_distance}km",
            ).add_to(m)
            m.fit_bounds(st.session_state.route_coordinates)

        if st.session_state.start and st.session_state.end:
            m.fit_bounds([st.session_state.start, st.session_state.end])

        return m
