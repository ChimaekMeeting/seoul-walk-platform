import streamlit as st
from src.db.connection import health_check

st.set_page_config(page_title="서울 산책 플랫폼", page_icon="🚶", layout="wide")
st.title("🚶 서울시 산책 경로 추천")
st.markdown("---")

db_ok = health_check()
st.sidebar.markdown("### 시스템 상태")
st.sidebar.success("🟢 DB 연결됨") if db_ok else st.sidebar.error("🔴 DB 연결 실패")

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("현재 날씨", "☀️ 맑음", "23°C")
with col2:
    st.metric("미세먼지", "🟢 좋음", "PM2.5: 12")
with col3:
    st.metric("추천 경로", "3개", "평균 3.2km")

st.info("팀원 분들, 담당 모듈을 작업한 후 이곳(app.py)에 조립해 주세요!")
