import os
import pydeck as pdk
import streamlit as st
from src.service.map_service import (
    fetch_kakao_facilities_df,
    fetch_local_db_points,
    fetch_local_db_lines,
)

# 맵박스 키 설정
MAPBOX_KEY = os.getenv("MAPBOX_API_KEY")

# 목표 지역 좌표 정의
LOCATIONS = {
    "🌸 상명대 벚꽃길 일대": {"center": (37.601, 126.955), "zoom": 15},
    "🌊 홍제천 ~ 연희동 일대": {"center": (37.573, 126.933), "zoom": 14.5},
    "🏠 남산 (기본)": {"center": (37.5522, 126.9806), "zoom": 14.5},
}


def render_map():
    # 1. UI 헤더 및 지역 선택
    selected_loc = st.selectbox("탐색 지역 선택", list(LOCATIONS.keys()))
    loc_info = LOCATIONS[selected_loc]
    curr_lat, curr_lon = loc_info["center"]

    # 2. 범례 표시
    st.markdown(
        """
        <div style="padding: 10px; background-color: #262730; color: white; border-radius: 5px; font-size: 12px; line-height:1.6;">
            <b>🛣️ 길:</b> <span style="color: #00BFFF;">━</span> 도보 네트워크 | 
            <b>🚩 안전:</b> <span style="color: #FFD700;">●</span> CCTV <span style="color: #FFFFE0;">●</span> 가로등 | <br>
            <b>📍 편의:</b> <span style="color: #FFA500;">●</span> 카페 <span style="color: #0064FF;">●</span> 편의점 
            <span style="color: #00BCD4;">●</span> 화장실 <span style="color: #FF1493;">●</span> 명소 <span style="color: #32CD32;">●</span> 공원
        </div>
    """,
        unsafe_allow_html=True,
    )

    layers = []

    # --- 🌟 레이어 1: 도보 네트워크 (가장 밑바탕) ---
    df_lines = fetch_local_db_lines(curr_lat, curr_lon)
    if not df_lines.empty:
        layers.append(
            pdk.Layer(
                "GeoJsonLayer",
                data=df_lines,
                get_line_color=[0, 191, 255, 100],
                get_line_width=3,
                line_width_min_pixels=2,
            )
        )

    # --- 🌟 레이어 2: 로컬 DB 기반 안전/인프라 점 데이터 ---
    db_configs = [
        {
            "table": "safety_layer",
            "col": "safety_type",
            "val": "cctv",
            "color": [255, 215, 0, 180],
            "name": "CCTV",
        },
        {
            "table": "safety_layer",
            "col": "safety_type",
            "val": "streetlight",
            "color": [255, 255, 224, 200],
            "name": "가로등",
        },
        {
            "table": "poi_layer",
            "col": "poi_type",
            "val": "park",
            "color": [50, 205, 50, 150],
            "name": "공원",
        },
    ]

    for cfg in db_configs:
        df_p = fetch_local_db_points(
            curr_lat, curr_lon, cfg["table"], cfg["col"], cfg["val"]
        )

        if not df_p.empty:
            # 🌟 툴팁에 표시될 진짜 이름(CCTV, 가로등 등)을 데이터프레임에 넣어줍니다.
            df_p["name"] = cfg["name"]

            layers.append(
                pdk.Layer(
                    "ScatterplotLayer",
                    data=df_p,
                    get_position=["lon", "lat"],
                    get_color=cfg["color"],
                    get_radius=20,
                    pickable=True,
                )
            )

    # --- 🌟 레이어 3: 카카오 API 기반 편의시설 ---
    kakao_configs = [
        {"code": "CE7", "color": [255, 165, 0], "name": "카페"},  # 주황색
        {"code": "CS2", "color": [0, 100, 255], "name": "편의점"},  # 파란색
        {"kw": "화장실", "color": [0, 188, 212], "name": "화장실"},  # 청록색 (중요!)
        {"code": "AT4", "color": [255, 20, 147], "name": "관광명소"},  # 진분홍색
        {"code": "FD6", "color": [139, 69, 19], "name": "음식점"},  # 갈색
    ]

    for k in kakao_configs:
        # 키워드 방식(kw)과 카테고리 방식(code)을 모두 지원하도록 수정된 서비스 함수 호출
        df_k = fetch_kakao_facilities_df(
            curr_lat, curr_lon, category_code=k.get("code"), keyword=k.get("kw")
        )

        if not df_k.empty:
            df_k["category_name"] = k["name"]  # 툴팁용 이름 추가
            layers.append(
                pdk.Layer(
                    "ScatterplotLayer",
                    data=df_k,
                    get_position=["lon", "lat"],
                    get_color=k["color"] + [160],  # 투명도 160 추가
                    get_radius=25,
                    pickable=True,
                )
            )

    # 3. 지도 렌더링
    st.pydeck_chart(
        pdk.Deck(
            layers=layers,
            initial_view_state=pdk.ViewState(
                latitude=curr_lat, longitude=curr_lon, zoom=loc_info["zoom"], pitch=45
            ),
            map_style="mapbox://styles/mapbox/dark-v10",  # 데이터가 돋보이는 다크 모드
            tooltip={"text": "{name}"},
        )
    )
