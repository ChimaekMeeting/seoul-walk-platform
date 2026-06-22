"""
frontend/streamlit_prototype/sections/auth.py

카카오 OAuth 로그인 게이트.
- 로그인 상태면 True를 반환하여 앱 진입을 허용한다.
- 미로그인 시 카카오 로그인 UI를 렌더링하고 False를 반환한다.
- 카카오 리다이렉트로 돌아온 경우(?code=...) 백엔드 콜백을 호출해
  access_token / refresh_token을 session_state에 저장한다.

주의: 카카오 리다이렉트가 이 Streamlit 앱으로 돌아오도록
KAKAO_REDIRECT_URI를 Streamlit 앱 URL(예: http://localhost:8501)로 설정해야 한다.
"""

import asyncio

import streamlit as st

from frontend.streamlit_prototype.api.login_router import LoginRouter


def _run_async(coro):
    """비동기 코루틴을 동기 컨텍스트에서 실행합니다."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def require_login() -> bool:
    """
    로그인 여부를 확인하고, 미로그인 시 카카오 로그인 UI를 렌더링합니다.

    Returns:
        bool: 로그인 완료 시 True, 그렇지 않으면 False.
    """
    if st.session_state.get("access_token"):
        return True

    login_router = LoginRouter()

    # 카카오 인가 코드를 들고 리다이렉트로 돌아온 경우
    code = st.query_params.get("code")
    if code:
        with st.spinner("로그인 처리 중..."):
            res, access_token, refresh_token = _run_async(login_router.kakao_callback(code))

        if access_token:
            st.session_state.access_token = access_token
            st.session_state.refresh_token = refresh_token
            st.session_state.nickname = res.get("nickname")
            st.query_params.clear()
            st.rerun()
        else:
            st.query_params.clear()
            st.error("로그인에 실패했습니다. 다시 시도해주세요.")

    # 로그인 화면
    st.subheader("🔐 로그인이 필요합니다")
    st.write("서비스를 이용하려면 카카오 로그인을 진행해주세요.")

    url_res = _run_async(login_router.get_kakao_login_url())
    login_url = url_res.get("url") if url_res else None

    if login_url:
        st.link_button("카카오로 로그인", login_url, type="primary", use_container_width=True)
    else:
        st.error("로그인 URL을 불러오지 못했습니다. 백엔드 서버 상태를 확인해주세요.")

    return False
