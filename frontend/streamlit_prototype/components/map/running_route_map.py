import os

import folium
import streamlit as st


class RunningRouteMap:

    def __init__(self):
        self.mapbox_token = os.getenv("MAPBOX_API_KEY")

    def build(self, center: list) -> folium.Map:
        """
        출발지·도착지 마커, 경로 폴리라인, DB 추천 코스 마커가 포함된 Folium 지도를 생성합니다.
        """
        m = folium.Map(location=center, zoom_start=14, tiles="cartodbpositron")

        if self.mapbox_token:
            folium.TileLayer(
                tiles=f"https://api.mapbox.com/styles/v1/mapbox/streets-v12/tiles/256/{{z}}/{{x}}/{{y}}?access_token={self.mapbox_token}",
                attr="Mapbox", name="Mapbox Streets",
            ).add_to(m)

        if st.session_state.start:
            folium.Marker(st.session_state.start, tooltip="출발지",
                          icon=folium.Icon(color="green", icon="play", prefix="fa")).add_to(m)
        if st.session_state.end:
            folium.Marker(st.session_state.end, tooltip="도착지",
                          icon=folium.Icon(color="red", icon="flag", prefix="fa")).add_to(m)

        result = st.session_state.result
        if result and result.get("coordinates"):
            coords = result["coordinates"]
            folium.PolyLine(
                locations=coords, color="#E53935", weight=5, opacity=0.85,
                tooltip=f"총 {result['total_distance_km']} km",
            ).add_to(m)
            m.fit_bounds(coords)

        if result:
            for course in result.get("matched_courses", []):
                folium.CircleMarker(
                    location=[course["start_lat"], course["start_lng"]],
                    radius=8, color="#1565C0", fill=True, fill_color="#42A5F5", fill_opacity=0.7,
                    tooltip=f"[{course['course_type']}] {course['name']} ({course.get('distance_m', 0) / 1000:.1f}km)",
                ).add_to(m)

        return m
