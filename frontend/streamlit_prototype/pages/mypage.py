"""
frontend/streamlit_prototype/pages/mypage.py

마이페이지 - 로그인 연동 버전
- st.session_state 기반 로그인 게이트 적용
- 로그아웃 API (POST /api/login/kakao/logout) 연동
- GET /api/user/me 연동
- PATCH /api/user/me 연동
- TODO: 산책기록팀 API 연동 후 산책 기록 섹션 실제 데이터로 교체
"""

import asyncio

import httpx
import streamlit as st

from frontend.streamlit_prototype.api.user_router import UserRouter
from frontend.streamlit_prototype.api.auth_client import call_with_auto_refresh
from datetime import datetime

_BACKEND_URL = "http://localhost:8000"
_AUTH_KEYS = ("access_token", "refresh_token", "nickname", "initialized", "thread_id")
_user_router = UserRouter()


def _clear_auth() -> None:
    for key in _AUTH_KEYS:
        st.session_state.pop(key, None)

st.set_page_config(page_title="마이페이지", page_icon="👤", layout="wide")

# ── 로그인 게이트 ─────────────────────────────────────────────────────────────
if not st.session_state.get("access_token"):
    st.warning("로그인이 필요합니다. 메인 페이지에서 로그인해주세요.")
    st.stop()
# ─────────────────────────────────────────────────────────────────────────────

def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _fetch_routes() -> list:
    """경로 기록을 API에서 조회합니다. 실패 시 빈 리스트 반환."""
    try:
        result = _run_async(
            call_with_auto_refresh(
                lambda token: _user_router.get_routes(token)
            )
        )
        return result.get("histories", [])
    except Exception:
        return []


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

    me = _run_async(call_with_auto_refresh(_user_router.get_me))
    if me.get("status") != "success":
        st.error("사용자 정보를 불러오지 못했습니다.")
        return

    nickname = me.get("nickname") or st.session_state.get("nickname", "알 수 없음")
    st.session_state["nickname"] = nickname

    col_info, col_btn = st.columns([3, 1])

    with col_info:
        st.markdown(f"**닉네임** &nbsp; {nickname}")

    with col_btn:
        if st.button("프로필 수정", use_container_width=True):
            st.session_state["edit_profile"] = True

    if st.session_state.get("edit_profile"):
        with st.form("profile_form"):
            new_nickname = st.text_input("닉네임", value=nickname)
            submitted = st.form_submit_button("저장")
            if submitted:
                result = _run_async(
                    call_with_auto_refresh(
                        lambda token: _user_router.patch_me(token, new_nickname)
                    )
                )
                if result.get("status") == "success":
                    st.session_state["nickname"] = result.get("nickname", new_nickname)
                    st.success("저장되었습니다.")
                    st.session_state["edit_profile"] = False
                    st.rerun()
                else:
                    st.error("저장에 실패했습니다.")


def render_stats(histories: list):
    st.divider()
    st.markdown("## 📊 산책 통계")

    total_count = len(histories)
    total_km    = round(sum(h.get("total_km", 0) for h in histories), 1)
    this_month  = datetime.now().month
    this_month_count = sum(
        1 for h in histories
        if datetime.fromisoformat(h["created_at"]).month == this_month
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("총 산책 횟수", f"{total_count}회")
    with col2:
        st.metric("총 산책 거리", f"{total_km} km")
    with col3:
        st.metric("이번 달 산책", f"{this_month_count}회")


def render_history(histories: list):
    st.divider()
    st.markdown("## 🗓️ 산책 기록")

    if not histories:
        st.info("아직 산책 기록이 없어요.")
        return

    for record in histories:
        with st.container(border=True):
            col1, col2, col3, col4 = st.columns([2, 2, 1, 1])
            with col1:
                date_str = record["created_at"][:10]
                st.markdown(f"**{date_str}**")
            with col2:
                st.markdown(record.get("mode", ""))
            with col3:
                st.markdown(f"{record.get('total_km', 0)} km")
            with col4:
                is_fav = record.get("is_favorite", False)
                label  = "★" if is_fav else "☆"
                if st.button(label, key=f"fav_{record['id']}"):
                    _run_async(
                        call_with_auto_refresh(
                            lambda token, rid=record["id"]: _user_router.toggle_favorite(token, rid)
                        )
                    )
                    st.rerun()


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


histories = _fetch_routes()

render_profile()
render_stats(histories)
render_history(histories)
render_logout()