import streamlit as st
from streamlit.components.v1 import html
from src.db.connection import health_check
from src.client.weather import get_environment_info

st.set_page_config(page_title="서울 산책 플랫폼", page_icon="🚶", layout="wide")
st.title("🚶 서울시 산책 경로 추천")
st.markdown("---")

# ── 브라우저에서 GPS 위치 받아오기 ───────────────────────────
html("""
<script>
navigator.geolocation.getCurrentPosition(
    function(pos) {
        const lat = pos.coords.latitude;
        const lng = pos.coords.longitude;
        const url = new URL(window.parent.location.href);
        url.searchParams.set("lat", lat);
        url.searchParams.set("lng", lng);
        window.parent.location.href = url.toString();
    },
    function(err) {
        console.log("위치 권한 거부:", err);
    }
);
</script>
""", height=0)

# URL 파라미터에서 위치 가져오기 (없으면 서울시청 기본값)
params = st.query_params
lat = float(params.get("lat", 37.5665))
lng = float(params.get("lng", 126.9780))

# 현재 위치 기반 날씨 가져오기
env = get_environment_info(lat=lat, lng=lng)

db_ok = health_check()
st.sidebar.markdown("### 시스템 상태")
st.sidebar.success("🟢 DB 연결됨") if db_ok else st.sidebar.error("🔴 DB 연결 실패")

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("현재 날씨", env["weather_status"], env["weather_msg"])
with col2:
    st.metric("미세먼지", env["air_status"], env["air_msg"])
with col3:
    st.metric("추천 경로", "3개", "평균 3.2km")

st.info("팀원 분들, 담당 모듈을 작업한 후 이곳(app.py)에 조립해 주세요!")