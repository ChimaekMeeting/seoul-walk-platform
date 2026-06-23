"""
frontend/streamlit_prototype/sections/auth.py

카카오 OAuth 로그인 게이트 + 토큰 영속화(브라우저 쿠키).

- access_token/refresh_token/nickname을 브라우저 쿠키에 저장해 새로고침·재접속에도
  로그인 상태를 유지한다. (st.session_state는 연결 단위라 새로고침 시 사라지므로 쿠키로 복원)
- 카카오 리다이렉트로 돌아온 경우(?code=...) 백엔드 콜백을 호출해 토큰을 발급받는다.

주의: 카카오 리다이렉트가 이 Streamlit 앱으로 돌아오도록
KAKAO_REDIRECT_URI를 Streamlit 앱 URL(예: http://localhost:8501)로 설정해야 한다.
"""

import asyncio
import datetime

import streamlit as st
import extra_streamlit_components as stx

from frontend.streamlit_prototype.api.login_router import LoginRouter

# 쿠키 유효기간(refresh_token 수명과 동일하게 14일)
_COOKIE_MAX_AGE_DAYS = 14


def get_cookie_manager() -> stx.CookieManager:
    """CookieManager 싱글톤. 위젯 중복(DuplicateWidgetID)을 막기 위해 1회만 생성합니다."""
    if "_cookie_manager_instance" not in st.session_state:
        st.session_state["_cookie_manager_instance"] = stx.CookieManager(key="cookie_manager")
    return st.session_state["_cookie_manager_instance"]


def _run_async(coro):
    """비동기 코루틴을 동기 컨텍스트에서 실행합니다."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _expires_at() -> datetime.datetime:
    return datetime.datetime.now() + datetime.timedelta(days=_COOKIE_MAX_AGE_DAYS)


def _persist_tokens(cm: stx.CookieManager, access_token: str, refresh_token: str, nickname) -> None:
    """발급된 토큰을 브라우저 쿠키에 저장합니다."""
    expires_at = _expires_at()
    cm.set("access_token", access_token, expires_at=expires_at, key="set_access_token")
    if refresh_token:
        cm.set("refresh_token", refresh_token, expires_at=expires_at, key="set_refresh_token")
    if nickname:
        cm.set("nickname", nickname, expires_at=expires_at, key="set_nickname")


def update_access_token_cookie(access_token: str) -> None:
    """자동 재발급으로 갱신된 access_token을 쿠키에도 반영합니다."""
    cm = get_cookie_manager()
    cm.set("access_token", access_token, expires_at=_expires_at(), key="update_access_token")


def clear_auth_cookies() -> None:
    """로그아웃/재발급 실패 시 인증 쿠키를 삭제합니다."""
    cm = get_cookie_manager()
    for name in ("access_token", "refresh_token", "nickname"):
        try:
            cm.delete(name, key=f"del_{name}")
        except Exception:
            pass


def _kakao_login_button_html(login_url: str) -> str:
    """카카오 공식 가이드 스타일(노란 배경 + 말풍선 심볼)의 로그인 버튼 HTML을 생성합니다."""
    return f'''
    <div style="display:flex; justify-content:center; margin-top:8px;">
      <a href="{login_url}" target="_self" style="
          display:flex; align-items:center; justify-content:center; gap:8px;
          width:300px; max-width:100%; box-sizing:border-box;
          height:48px; padding:0 16px;
          background-color:#FEE500; border-radius:12px;
          color:rgba(0,0,0,0.85); font-size:16px; font-weight:700;
          text-decoration:none;
          font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif;">
        <svg width="20" height="20" viewBox="0 0 18 18" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M9 1C4.589 1 1 3.79 1 7.236c0 2.231 1.452 4.188 3.638 5.293-.16.598-.578 2.165-.662 2.502-.103.418.153.412.323.3.133-.089 2.107-1.43 2.962-2.012.563.083 1.145.127 1.739.127 4.411 0 8-2.79 8-6.21C17 3.79 13.411 1 9 1z" fill="#000000"/>
        </svg>
        <span>카카오 로그인</span>
      </a>
    </div>
    '''

def require_login() -> bool:
    # 1) session_state 체크 (stx 전혀 건드리지 않음)
    if st.session_state.get("access_token"):
        return True

    # 2) 카카오 인가 코드 처리 (stx 없이)
    code = st.query_params.get("code")
    if code and not st.session_state.get("_kakao_callback_done"):
        st.session_state["_kakao_callback_done"] = True
        login_router = LoginRouter()
        with st.spinner("로그인 처리 중..."):
            res, access_token, refresh_token = _run_async(login_router.kakao_callback(code))
        if access_token:
            st.session_state.access_token = access_token
            st.session_state.refresh_token = refresh_token
            st.session_state.nickname = res.get("nickname")
            st.query_params.clear()
            st.rerun()
        else:
            st.error("로그인에 실패했습니다. 다시 시도해주세요.")
        return False

    # 3) 브라우저 쿠키에서 복원 (새로고침/재접속 시)
    cm = get_cookie_manager()
    cookies = cm.get_all() or {}
    if cookies.get("access_token"):
        st.session_state.access_token = cookies.get("access_token")
        st.session_state.refresh_token = cookies.get("refresh_token")
        st.session_state.nickname = cookies.get("nickname")
        return True

    # 4) 로그인 화면
    login_router = LoginRouter()
    url_res = _run_async(login_router.get_kakao_login_url())
    login_url = url_res.get("url") if url_res else None
    if login_url:
        st.markdown(_kakao_login_button_html(login_url), unsafe_allow_html=True)
    else:
        st.error("로그인 URL을 불러오지 못했습니다. 백엔드 서버 상태를 확인해주세요.")
    return False
