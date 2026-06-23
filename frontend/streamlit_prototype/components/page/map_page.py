import pydeck as pdk
import streamlit as st

from frontend.streamlit_prototype.components.layer.map_layer import MapLayer


class MapPage:

    LOCATIONS = {
        "🌸 상명대 벚꽃길 일대": {"center": (37.601, 126.955), "zoom": 15},
        "🌊 홍제천 ~ 연희동 일대": {"center": (37.573, 126.933), "zoom": 14.5},
        "🏠 남산 (기본)": {"center": (37.5522, 126.9806), "zoom": 14.5},
    }

    DB_LAYER_CONFIGS = [
        {"layer": "safety", "category": "cctv",        "color": [255, 215, 0],   "name": "CCTV"},
        {"layer": "safety", "category": "streetlight", "color": [255, 255, 224], "name": "가로등"},
    ]

    def __init__(self):
        self.map_layer = MapLayer()

    def _build_layers(self, curr_lat: float, curr_lon: float) -> list:
        """
        PyDeck 렌더링에 사용할 레이어 목록을 생성하여 반환합니다.
        """
        layers = []

        df_lines = self.map_layer.fetch_local_db_lines_optimized(curr_lat, curr_lon)
        if not df_lines.empty:
            layers.append(
                pdk.Layer(
                    "PathLayer",
                    data=df_lines,
                    get_path="path",
                    get_color=[0, 191, 255, 120],
                    get_width=3,
                    width_min_pixels=1.5,
                    pickable=True,
                )
            )

        for cfg in self.DB_LAYER_CONFIGS:
            # 레이어 전체를 받아(캐시됨) category로 클라이언트 필터링
            df_p = self.map_layer.fetch_local_db_points(curr_lat, curr_lon, cfg["layer"])
            if not df_p.empty and "category" in df_p.columns:
                df_p = df_p[df_p["category"] == cfg["category"]]
            if not df_p.empty:
                df_p = df_p.copy()
                df_p["name"] = cfg["name"]
                layers.append(
                    pdk.Layer(
                        "ScatterplotLayer",
                        data=df_p,
                        get_position=["lon", "lat"],
                        get_color=cfg["color"] + [180],
                        get_radius=15,
                        pickable=True,
                    )
                )

        return layers

    def render(self):
        """
        지역 선택 UI와 PyDeck 지도를 Streamlit 페이지에 렌더링합니다.
        """
        st.title("🚶‍♀️ 서울시 안전 도보 네트워크")
        selected_loc = st.selectbox("탐색 지역 선택", list(self.LOCATIONS.keys()))
        loc_info = self.LOCATIONS[selected_loc]
        curr_lat, curr_lon = loc_info["center"]

        st.markdown(
            """
            <div style="padding: 10px; background-color: #262730; color: white; border-radius: 5px; font-size: 12px; line-height:1.6;">
                <b>🛣️ 길:</b> <span style="color: #00BFFF;">━</span> 도보 네트워크 (GPU 가속) |
                <b>🚩 안전:</b> <span style="color: #FFD700;">●</span> CCTV <span style="color: #FFFFE0;">●</span> 가로등 | <br>
                <b>📍 편의:</b> <span style="color: #FFA500;">●</span> 카페 <span style="color: #0064FF;">●</span> 편의점
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.pydeck_chart(
            pdk.Deck(
                layers=self._build_layers(curr_lat, curr_lon),
                initial_view_state=pdk.ViewState(
                    latitude=curr_lat, longitude=curr_lon, zoom=loc_info["zoom"], pitch=45
                ),
                map_style="mapbox://styles/mapbox/dark-v10",
                tooltip={"text": "{name}\nID: {link_id}"},
            )
        )