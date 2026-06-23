"""
[테스트 전용] 로그인 없이 테스트 유저의 경로 기록을 확인하는 페이지.
실제 서비스에서는 사용하지 않습니다.
scripts/insert_test_route_history.py 로 삽입한 데이터를 확인합니다.
"""
import config.path_setup  # noqa: F401

import folium
import streamlit as st
from streamlit_folium import st_folium
from datetime import datetime, timezone

from src.repository.user.route_history_repository import RouteHistoryRepository
from src.interfaces.schema.user_schema import RouteHistoryItem, RouteHistoryResponse

_TEST_USER_ID = 2

_MODE_LABELS: dict[str, str] = {
    "circular_random":  "순환 산책",
    "circular_child":   "어린이 동반 순환",
    "circular_running": "러닝·조깅 순환",
    "oneway_shortest":  "최단 거리 편도",
    "oneway_random":    "거리 설정 편도",
    "oneway_child":     "어린이 동반 편도",
    "oneway_running":   "러닝·조깅 편도",
}

st.set_page_config(page_title="[테스트] 산책 기록", page_icon="🧪", layout="wide")
st.markdown("# 🧪 산책 기록 테스트 (로그인 없음)")
st.caption(f"테스트 유저 ID: {_TEST_USER_ID} | scripts/insert_test_route_history.py 데이터")


@st.cache_data(ttl=30, show_spinner=False)
def _load_histories(user_id: int) -> list[dict]:
    rows = RouteHistoryRepository.find_by_user_id(user_id)
    return [RouteHistoryItem.model_validate(r).model_dump(mode="json") for r in rows]


def _render_map(history: dict) -> None:
    coords = history["coordinates"]
    if not coords:
        st.warning("경로 좌표가 없습니다.")
        return

    center = coords[len(coords) // 2]
    m = folium.Map(location=center, zoom_start=15, tiles="cartodbpositron")

    folium.Marker(coords[0], tooltip="출발지",
                  icon=folium.Icon(color="green", icon="play", prefix="fa")).add_to(m)

    if history.get("destination_lat") and history.get("destination_lon"):
        folium.Marker(
            [history["destination_lat"], history["destination_lon"]],
            tooltip="도착지",
            icon=folium.Icon(color="red", icon="flag", prefix="fa"),
        ).add_to(m)
    else:
        folium.Marker(coords[-1], tooltip="도착지",
                      icon=folium.Icon(color="red", icon="flag", prefix="fa")).add_to(m)

    folium.PolyLine(coords, color="#4A90E2", weight=6, opacity=0.8,
                    tooltip=f"총 {history['total_km']} km").add_to(m)
    m.fit_bounds(coords)
    st_folium(m, use_container_width=True, height=450, returned_objects=[])


with st.spinner("기록 불러오는 중..."):
    try:
        histories = _load_histories(_TEST_USER_ID)
    except Exception as e:
        st.error(f"DB 조회 실패: {e}")
        histories = []

# 통계
col1, col2, col3 = st.columns(3)
now = datetime.now(timezone.utc)
this_month = sum(
    1 for h in histories
    if datetime.fromisoformat(h["created_at"]).replace(tzinfo=timezone.utc).month == now.month
    and datetime.fromisoformat(h["created_at"]).replace(tzinfo=timezone.utc).year == now.year
)
with col1:
    st.metric("총 산책 횟수", f"{len(histories)}회")
with col2:
    st.metric("총 산책 거리", f"{round(sum(h['total_km'] for h in histories), 1)} km")
with col3:
    st.metric("이번 달 산책", f"{this_month}회")

st.divider()
st.markdown("## 🗓️ 산책 기록")

if not histories:
    st.info("기록이 없습니다. scripts/insert_test_route_history.py 를 먼저 실행하세요.")
else:
    selected_id = st.session_state.get("selected_history_id")
    for h in histories:
        created_at = datetime.fromisoformat(h["created_at"]).replace(tzinfo=timezone.utc)
        date_str = created_at.strftime("%Y-%m-%d %H:%M")
        mode_label = _MODE_LABELS.get(h["mode"], h["mode"])
        time_min = round(h["total_km"] / 4.0 * 60)
        is_selected = h["id"] == selected_id
        is_favorite = h.get("is_favorite", False)

        with st.container(border=True):
            col1, col2, col3, col4, col5, col6 = st.columns([2, 2, 1, 1, 1, 1])
            with col1:
                st.markdown(f"**{date_str}**")
            with col2:
                st.markdown(mode_label)
            with col3:
                st.markdown(f"{h['total_km']} km")
            with col4:
                st.markdown(f"약 {time_min}분")
            with col5:
                fav_label = "★ 저장됨" if is_favorite else "☆ 저장"
                if st.button(fav_label, key=f"fav_{h['id']}"):
                    RouteHistoryRepository.toggle_favorite(h["id"], _TEST_USER_ID)
                    st.cache_data.clear()
                    st.rerun()
            with col6:
                map_label = "닫기" if is_selected else "지도 보기"
                if st.button(map_label, key=f"btn_{h['id']}"):
                    if is_selected:
                        st.session_state.pop("selected_history_id", None)
                    else:
                        st.session_state["selected_history_id"] = h["id"]
                    st.rerun()

            if is_selected:
                _render_map(h)
