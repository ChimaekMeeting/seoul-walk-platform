"""
frontend/streamlit_prototype/pages/mypage.py

마이페이지 - 로그인 연동 버전
- st.session_state 기반 로그인 게이트 적용
- 로그아웃 API (POST /api/login/kakao/logout) 연동
- TODO: GET /api/user/me 연동 후 display_id, created_at 실제 데이터로 교체
- TODO: 산책기록팀 API 연동 후 산책 기록 섹션 실제 데이터로 교체
"""

import asyncio

import httpx
import streamlit as st

_BACKEND_URL = "http://localhost:8000"
_AUTH_KEYS = ("access_token", "refresh_token", "nickname", "initialized", "thread_id")


def _clear_auth() -> None:
    for key in _AUTH_KEYS:
        st.session_state.pop(key, None)

st.set_page_config(page_title="마이페이지", page_icon="👤", layout="wide")

# ── 로그인 게이트 ─────────────────────────────────────────────────────────────
if not st.session_state.get("access_token"):
    st.warning("로그인이 필요합니다. 메인 페이지에서 로그인해주세요.")
    st.stop()
# ─────────────────────────────────────────────────────────────────────────────


# ── Mock 데이터 ──────────────────────────────────────────────────────────────
MOCK_STATS = {
    "total_count": 12,
    "total_km": 45.3,
    "this_month_count": 3,
}

MOCK_HISTORY = [
    {"date": "2024-06-20", "mode": "순환 랜덤",    "total_km": 4.2, "time_min": 63},
    {"date": "2024-06-17", "mode": "편도 최단거리", "total_km": 2.8, "time_min": 42},
    {"date": "2024-06-14", "mode": "순환 어린이",   "total_km": 3.5, "time_min": 53},
    {"date": "2024-06-10", "mode": "편도 랜덤",     "total_km": 5.1, "time_min": 77},
    {"date": "2024-06-05", "mode": "순환 러닝",     "total_km": 6.0, "time_min": 90},
]
# ─────────────────────────────────────────────────────────────────────────────


def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


async def _call_logout():
    """백엔드 로그아웃 API를 호출합니다."""
    cookies = {}
    access_token = st.session_state.get("access_token")
    refresh_token = st.session_state.get("refresh_token")
    if access_token:
        cookies["access_token"] = access_token
    if refresh_token:
        cookies["refresh_token"] = refresh_token
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(f"{_BACKEND_URL}/api/login/kakao/logout", cookies=cookies)


def render_profile():
    st.markdown("## 👤 프로필")

    nickname = st.session_state.get("nickname", "알 수 없음")

    col_info, col_btn = st.columns([3, 1])

    with col_info:
        st.markdown(f"**닉네임** &nbsp; {nickname}")
        # TODO: GET /api/user/me 연동 후 display_id, created_at 실제 데이터로 교체

    with col_btn:
        if st.button("프로필 수정", use_container_width=True):
            st.session_state["edit_profile"] = True

    if st.session_state.get("edit_profile"):
        with st.form("profile_form"):
            new_nickname = st.text_input("닉네임", value=nickname)
            submitted = st.form_submit_button("저장")
            if submitted:
                # TODO: PATCH /api/user/me 호출로 교체
                st.success("저장되었습니다. (Mock)")
                st.session_state["edit_profile"] = False


def render_stats():
    st.divider()
    st.markdown("## 📊 산책 통계")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("총 산책 횟수", f"{MOCK_STATS['total_count']}회")
    with col2:
        st.metric("총 산책 거리", f"{MOCK_STATS['total_km']} km")
    with col3:
        st.metric("이번 달 산책", f"{MOCK_STATS['this_month_count']}회")


def render_history():
    st.divider()
    st.markdown("## 🗓️ 산책 기록")

    # TODO: GET /api/walk/history 호출로 교체
    for record in MOCK_HISTORY:
        with st.container(border=True):
            col1, col2, col3, col4 = st.columns([2, 2, 1, 1])
            with col1:
                st.markdown(f"**{record['date']}**")
            with col2:
                st.markdown(record["mode"])
            with col3:
                st.markdown(f"{record.get('total_km', 0)} km")
            with col4:
                st.markdown(f"{record['time_min']} 분")


def render_logout():
    st.divider()
    if st.button("로그아웃", type="secondary"):
        with st.spinner("로그아웃 중..."):
            try:
                _run_async(_call_logout())
            except Exception:
                pass
        _clear_auth()
        st.rerun()


render_profile()
render_stats()
render_history()
render_logout()
