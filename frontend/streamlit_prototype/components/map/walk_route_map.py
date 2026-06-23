import os
import time

import folium
import streamlit as st
from streamlit.components.v1 import html
from streamlit_folium import st_folium

from frontend.streamlit_prototype.components.layer.nature_layer import NatureLayer
from frontend.streamlit_prototype.components.layer.map_layer import MapLayer


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
        self.nature_layer = NatureLayer()
        self.map_layer = MapLayer()

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

    def render(self, input_mode: str) -> None:
        """
        설정 모드 선택, 지도 렌더링, 클릭 이벤트 처리를 포함한 대화형 지도 섹션을 렌더링합니다.
        """
        if input_mode == "직접 설정":
            st.radio(
                "설정 모드",
                options=["start", "end"],
                format_func=lambda x: "출발지 설정" if x == "start" else "도착지 설정",
                horizontal=True,
                key="mode",
            )
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

    def _add_nature_markers(self, m: folium.Map, center_lat: float, center_lon: float) -> None:
        """
        자연 마커를 Folium 지도에 추가합니다.
        """
        df_nature = self.map_layer.fetch_local_db_points(
            center_lat, center_lon, "nature", radius_m=1000
        )
        if not df_nature.empty:
            for _, row in df_nature.iterrows():
                folium.CircleMarker(
                    location=[row["lat"], row["lon"]],
                    radius=3,
                    color="#2ECC71",
                    fill=True,
                    fill_color="#2ECC71",
                    fill_opacity=0.7,
                    tooltip=row.get("green_type", "자연"),
                ).add_to(m)

    def build(self, center: list) -> folium.Map:
        """
        세션 상태를 기반으로 마커, 경로 폴리라인, 자연·도보 네트워크 오버레이가 포함된 Folium 지도를 생성합니다.
        """
        m = folium.Map(location=center, zoom_start=15, tiles="cartodbpositron")

        if self.mapbox_token:
            folium.TileLayer(
                tiles=f"https://api.mapbox.com/styles/v1/mapbox/streets-v12/tiles/256/{{z}}/{{x}}/{{y}}?access_token={self.mapbox_token}",
                attr="Mapbox", name="Mapbox Streets",
            ).add_to(m)

        if st.session_state.start:
            folium.Marker(
                st.session_state.start, popup="출발지", tooltip="출발지",
                icon=folium.Icon(color="green", icon="play", prefix="fa"),
            ).add_to(m)
        if st.session_state.end:
            folium.Marker(
                st.session_state.end, popup="도착지", tooltip="도착지",
                icon=folium.Icon(color="red", icon="flag", prefix="fa"),
            ).add_to(m)

        if st.session_state.route_coordinates:
            folium.PolyLine(
                locations=st.session_state.route_coordinates,
                color="#4A90E2", weight=6, opacity=0.8,
                tooltip=f"총 {st.session_state.route_distance}km",
            ).add_to(m)
            m.fit_bounds(st.session_state.route_coordinates)

            if st.session_state.get("route_result"):
                self.nature_layer.add_to_map(
                    m, center[0], center[1],
                    st.session_state.route_coordinates,
                )
                self._add_nature_markers(m, center[0], center[1])

        if st.session_state.start and st.session_state.end:
            m.fit_bounds([st.session_state.start, st.session_state.end])

        return m
