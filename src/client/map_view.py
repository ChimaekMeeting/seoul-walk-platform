import pydeck as pdk
import streamlit as st
import os
from dotenv import load_dotenv
from src.service.map_service import (
    fetch_kakao_facilities_df,
    fetch_local_db_points,
    fetch_local_db_lines_optimized
)

# .env 파일 로드 (Mapbox 키 등 환경변수 확인용)
load_dotenv()

LOCATIONS = {
    "🌸 상명대 벚꽃길 일대": {"center": (37.601, 126.955), "zoom": 15},
    "🌊 홍제천 ~ 연희동 일대": {"center": (37.573, 126.933), "zoom": 14.5},
    "🏠 남산 (기본)": {"center": (37.5522, 126.9806), "zoom": 14.5},
}

@st.cache_data(ttl=600)
def get_cached_walk_network(lat, lon):
    return fetch_local_db_lines_optimized(lat, lon)

def render_map():
    # 1. UI 헤더 및 지역 선택
    st.title("🚶‍♀️ 서울시 안전 도보 네트워크")
    selected_loc = st.selectbox("탐색 지역 선택", list(LOCATIONS.keys()))
    loc_info = LOCATIONS[selected_loc]
    curr_lat, curr_lon = loc_info["center"]

    # 2. 범례
    st.markdown("""
        <div style="padding: 10px; background-color: #262730; color: white; border-radius: 5px; font-size: 12px; line-height:1.6;">
            <b>🛣️ 길:</b> <span style="color: #00BFFF;">━</span> 도보 네트워크 (GPU 가속) | 
            <b>🚩 안전:</b> <span style="color: #FFD700;">●</span> CCTV <span style="color: #FFFFE0;">●</span> 가로등 | <br>
            <b>📍 편의:</b> <span style="color: #FFA500;">●</span> 카페 <span style="color: #0064FF;">●</span> 편의점 
        </div>
    """, unsafe_allow_html=True)

    layers = []

    # --- 🌟 레이어 1: 최적화된 도보 네트워크 (PathLayer) ---
    df_lines = get_cached_walk_network(curr_lat, curr_lon)
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

    # --- 🌟 레이어 2: 로컬 DB 기반 안전 시설물 ---
    db_configs = [
        {"table": "safety_layer", "col": "safety_type", "val": "cctv", "color": [255, 215, 0], "name": "CCTV"},
        {"table": "safety_layer", "col": "safety_type", "val": "streetlight", "color": [255, 255, 224], "name": "가로등"},
    ]

    for cfg in db_configs:
        df_p = fetch_local_db_points(curr_lat, curr_lon, cfg["table"], cfg["col"], cfg["val"])
        if not df_p.empty:
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

    # 3. 최종 지도 렌더링
    st.pydeck_chart(
        pdk.Deck(
            layers=layers,
            initial_view_state=pdk.ViewState(
                latitude=curr_lat, longitude=curr_lon, zoom=loc_info["zoom"], pitch=45
            ),
            map_style="mapbox://styles/mapbox/dark-v10",
            tooltip={"text": "{name}\nID: {link_id}"}
        )
    )

# --- 실행부 추가 ---
if __name__ == "__main__":
    render_map()