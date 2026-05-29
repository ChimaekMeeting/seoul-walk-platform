import os

import folium
import streamlit as st

from src.service.route.route_flat import draw_route_connectors
from frontend.streamlit_prototype.components.layer.poi_layer import PoiLayer


class RouteMap:

    def __init__(self, G):
        self.mapbox_token = os.getenv("MAPBOX_API_KEY")
        self.G = G
        self.poi_layer = PoiLayer()

    def build(self, center: list) -> folium.Map:
        """
        세션 상태를 기반으로 출발지·도착지 마커, 경로 폴리라인, POI 오버레이가 포함된 Folium 지도를 생성합니다.
        """
        m = folium.Map(location=center, zoom_start=15, tiles="cartodbpositron")

        if self.mapbox_token:
            folium.TileLayer(
                tiles=f"https://api.mapbox.com/styles/v1/mapbox/streets-v12/tiles/256/{{z}}/{{x}}/{{y}}?access_token={self.mapbox_token}",
                attr="Mapbox", name="Mapbox Streets",
            ).add_to(m)

        if st.session_state.start:
            folium.Marker(st.session_state.start, popup="출발지", tooltip="출발지",
                          icon=folium.Icon(color="green", icon="play", prefix="fa")).add_to(m)
        if st.session_state.end:
            folium.Marker(st.session_state.end, popup="도착지", tooltip="도착지",
                          icon=folium.Icon(color="red", icon="flag", prefix="fa")).add_to(m)

        if st.session_state.route_coordinates:
            folium.PolyLine(
                locations=st.session_state.route_coordinates, color="#4A90E2", weight=6, opacity=0.8,
                tooltip=f"총 {st.session_state.route_distance}km",
            ).add_to(m)
            m.fit_bounds(st.session_state.route_coordinates)
            draw_route_connectors(m, st.session_state.start, st.session_state.end, st.session_state.route_coordinates)

            if st.session_state.get("route_result"):
                self.poi_layer.add_to_map(
                    m, center[0], center[1],
                    st.session_state.route_result["nodes"], self.G,
                )

        if st.session_state.start and st.session_state.end:
            m.fit_bounds([st.session_state.start, st.session_state.end])

        return m
