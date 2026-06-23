"""
frontend/streamlit_prototype/pages/route_history.py

산책 기록 페이지
- GET /api/user/routes 로 경로 기록 목록 조회
- GET /api/user/routes/{id} 로 상세 경로를 지도에 표시
"""

import asyncio
import config.path_setup  # noqa: F401

import folium
import streamlit as st
from streamlit_folium import st_folium

from frontend.streamlit_prototype.api.user_router import UserRouter

_MODE_LABELS: dict[str, str] = {
    "circular_random":  "순환 산책",
    "circular_child":   "어린이 동반 순환",
    "circular_running": "러닝·조깅 순환",
    "oneway_shortest":  "최단 거리 편도",
    "oneway_random":    "거리 설정 편도",
    "oneway_child":     "어린이 동반 편도",
    "oneway_running":   "러닝·조깅 편도",
}

st.set_page_config(page_title="산책 기록", page_icon="🗺️", layout="wide")

if not st.session_state.get("access_token"):
    st.warning("로그인이 필요합니다. 메인 페이지에서 로그인해주세요.")
    st.stop()


def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_histories(access_token: str) -> list[dict]:
    router = UserRouter()
    data = _run_async(router.get_route_histories(access_token))
    return data.get("histories", [])


def _render_route_map(history: dict) -> None:
    coords = history["coordinates"]
    if not coords:
        st.warning("경로 좌표 데이터가 없습니다.")
        return

    center = coords[len(coords) // 2]
    m = folium.Map(location=center, zoom_start=15, tiles="cartodbpositron")

    folium.Marker(
        coords[0], tooltip="출발지",
        icon=folium.Icon(color="green", icon="play", prefix="fa"),
    ).add_to(m)

    if history.get("destination_lat") and history.get("destination_lon"):
        folium.Marker(
            [history["destination_lat"], history["destination_lon"]],
            tooltip="도착지",
            icon=folium.Icon(color="red", icon="flag", prefix="fa"),
        ).add_to(m)
    else:
        folium.Marker(
            coords[-1], tooltip="도착지",
            icon=folium.Icon(color="red", icon="flag", prefix="fa"),
        ).add_to(m)

    folium.PolyLine(
        locations=coords, color="#4A90E2", weight=6, opacity=0.8,
        tooltip=f"총 {history['total_km']} km",
    ).add_to(m)
    m.fit_bounds(coords)

    st_folium(m, use_container_width=True, height=450, returned_objects=[])


def _render_history_list(histories: list[dict]) -> None:
    st.markdown("## 🗓️ 산책 기록")

    if not histories:
        st.info("아직 산책 기록이 없습니다. 경로를 추천받고 첫 산책을 기록해보세요!")
        return

    selected_id = st.session_state.get("selected_history_id")

    for h in histories:
        from datetime import datetime, timezone
        created_at = datetime.fromisoformat(h["created_at"]).replace(tzinfo=timezone.utc)
        date_str = created_at.strftime("%Y-%m-%d %H:%M")
        mode_label = _MODE_LABELS.get(h["mode"], h["mode"])
        time_min = round(h["total_km"] / 4.0 * 60)
        is_selected = h["id"] == selected_id

        with st.container(border=True):
            col1, col2, col3, col4, col5 = st.columns([2, 2, 1, 1, 1])
            with col1:
                st.markdown(f"**{date_str}**")
            with col2:
                st.markdown(mode_label)
            with col3:
                st.markdown(f"{h['total_km']} km")
            with col4:
                st.markdown(f"약 {time_min}분")
            with col5:
                label = "닫기" if is_selected else "지도 보기"
                if st.button(label, key=f"btn_{h['id']}"):
                    if is_selected:
                        st.session_state.pop("selected_history_id", None)
                    else:
                        st.session_state["selected_history_id"] = h["id"]
                    st.rerun()

            if is_selected:
                _render_route_map(h)


# ── 메인 렌더링 ───────────────────────────────────────────────────────────────
st.markdown("# 🗺️ 산책 기록")

access_token = st.session_state.get("access_token", "")

with st.spinner("기록을 불러오는 중..."):
    try:
        histories = _fetch_histories(access_token)
    except Exception as e:
        st.error(f"기록을 불러오지 못했습니다: {e}")
        histories = []

col_stat1, col_stat2, col_stat3 = st.columns(3)
with col_stat1:
    st.metric("총 산책 횟수", f"{len(histories)}회")
with col_stat2:
    total_km = round(sum(h["total_km"] for h in histories), 1)
    st.metric("총 산책 거리", f"{total_km} km")
with col_stat3:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    this_month = sum(
        1 for h in histories
        if datetime.fromisoformat(h["created_at"]).replace(tzinfo=timezone.utc).month == now.month
        and datetime.fromisoformat(h["created_at"]).replace(tzinfo=timezone.utc).year == now.year
    )
    st.metric("이번 달 산책", f"{this_month}회")

st.divider()
_render_history_list(histories)
