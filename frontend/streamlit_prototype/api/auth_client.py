"""
frontend/streamlit_prototype/api/auth_client.py

access_token 만료를 감지해 refresh_token으로 자동 재발급한 뒤 원래 요청을
1회 재시도하는 reactive 래퍼.

- prewalk 응답:  status == "access_expired_token"
- walk 응답:     status == "FAILED" and fallback_reason == "access_expired_token"
위 두 형태 모두를 "access_token 만료"로 인식한다.
"""

import streamlit as st

from frontend.streamlit_prototype.api.auth_router import AuthRouter

# 재발급 시 함께 비워야 하는 인증/세션 관련 키
_AUTH_KEYS = ("access_token", "refresh_token", "nickname", "initialized", "thread_id")


def _is_access_expired(response: dict) -> bool:
    """응답이 access_token 만료를 의미하는지 판별합니다."""
    if not isinstance(response, dict):
        return False
    if response.get("status") == "access_expired_token":
        return True
    if response.get("status") == "FAILED" and response.get("fallback_reason") == "access_expired_token":
        return True
    return False


def clear_auth() -> None:
    """인증/세션 상태(session_state + 브라우저 쿠키)를 비워 재로그인을 유도합니다."""
    for key in _AUTH_KEYS:
        st.session_state.pop(key, None)
    try:
        from frontend.streamlit_prototype.sections.auth import clear_auth_cookies
        clear_auth_cookies()
    except Exception:
        pass


async def _refresh_access_token() -> bool:
    """
    refresh_token으로 access_token을 재발급해 session_state에 저장합니다.
    성공 시 True, 실패 시 인증 상태를 비우고 False를 반환합니다.
    """
    refresh_token = st.session_state.get("refresh_token")
    if not refresh_token:
        return False

    res, new_access_token = await AuthRouter().check_refresh_token(refresh_token)

    if (res or {}).get("status") == "success" and new_access_token:
        st.session_state.access_token = new_access_token
        # 갱신된 토큰을 쿠키에도 반영해 새로고침 후에도 이어지게 합니다.
        try:
            from frontend.streamlit_prototype.sections.auth import update_access_token_cookie
            update_access_token_cookie(new_access_token)
        except Exception:
            pass
        return True

    # refresh_token도 만료/무효 → 재로그인 필요
    clear_auth()
    return False


async def call_with_auto_refresh(request_fn):
    """
    access_token 만료를 자동 처리하는 래퍼.

    Args:
        request_fn: access_token(str)을 받아 응답 dict를 반환하는 async 콜러블.

    Returns:
        dict: 요청 응답. 만료 감지 시 재발급 후 재시도한 결과.
    """
    access_token = st.session_state.get("access_token")
    response = await request_fn(access_token)

    if _is_access_expired(response):
        if await _refresh_access_token():
            response = await request_fn(st.session_state.get("access_token"))

    return response
