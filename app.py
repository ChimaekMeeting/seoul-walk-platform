import streamlit as st
from src.db.connection import health_check
from src.api.weather import get_environment_info

st.set_page_config(page_title="서울 산책 플랫폼", page_icon="🚶", layout="wide")
st.title("🚶 서울시 산책 경로 추천")
st.markdown("---")

db_ok = health_check()
st.sidebar.markdown("### 시스템 상태")
st.sidebar.success("🟢 DB 연결됨") if db_ok else st.sidebar.error("🔴 DB 연결 실패")

# 실제 API 데이터 가져오기
env = get_environment_info()

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("현재 날씨", env["weather_status"], env["weather_msg"])
with col2:
    st.metric("미세먼지", env["air_status"], env["air_msg"])
with col3:
    st.metric("추천 경로", "3개", "평균 3.2km")

st.info("팀원 분들, 담당 모듈을 작업한 후 이곳(app.py)에 조립해 주세요!")