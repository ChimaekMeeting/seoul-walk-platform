import os

import folium
import streamlit as st

from frontend.streamlit_prototype.components.layer.poi_layer import PoiLayer
from frontend.streamlit_prototype.components.layer.map_layer import MapLayer


class WalkRouteMap:

    def __init__(self, G):
        self.mapbox_token = os.getenv("MAPBOX_API_KEY")
        self.G = G
        self.poi_layer = PoiLayer()
        self.map_layer = MapLayer()

    def _add_poi_markers(self, m: folium.Map, center_lat: float, center_lon: float):
        """
        POI 마커를 Folium 지도에 추가합니다.
        """
        df_poi = self.map_layer.fetch_local_db_points(
            center_lat, center_lon, "poi_layer", "poi_type", None, radius_m=1000
        )
        if not df_poi.empty:
            for _, row in df_poi.iterrows():
                folium.CircleMarker(
                    location=[row["lat"], row["lon"]],
                    radius=3,
                    color="#2ECC71",
                    fill=True,
                    fill_color="#2ECC71",
                    fill_opacity=0.7,
                    tooltip=row.get("poi_type", "POI"),
                ).add_to(m)

    def build(self, center: list) -> folium.Map:
        """
        세션 상태를 기반으로 마커, 경로 폴리라인, POI·CCTV·도보 네트워크 오버레이가 포함된 Folium 지도를 생성합니다.
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
                self.poi_layer.add_to_map(
                    m, center[0], center[1],
                    st.session_state.route_result["nodes"], self.G,
                )
                self._add_poi_markers(m, center[0], center[1])

        if st.session_state.start and st.session_state.end:
            m.fit_bounds([st.session_state.start, st.session_state.end])

        return m
