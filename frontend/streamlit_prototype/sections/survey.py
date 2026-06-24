"""
frontend/streamlit_prototype/sections/survey.py

온보딩 설문 UI. 로그인 직후 survey_completed = False인 사용자에게 노출.
SURVEY_TAGS 키워드 선택 + 선호 거리 선택 후 제출하면 UserPreference에 저장된다.
"""
import asyncio
import streamlit as st

from frontend.streamlit_prototype.api.survey_router import SurveyRouter
from src.service.user.survey_service import SURVEY_TAGS


def _run_async(coro):
    """비동기 코루틴을 동기 컨텍스트에서 실행합니다."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def require_survey() -> bool:
    """
    설문 완료 여부를 확인하고, 미완료 시 설문 UI를 렌더링합니다.
    완료 or 스킵 시 True, 설문 진행 중이면 False를 반환합니다.
    """
    # 이미 완료된 경우
    if st.session_state.get("survey_completed"):
        return True

    # API로 완료 여부 확인 (1회)
    if "survey_status_checked" not in st.session_state:
        st.session_state["survey_status_checked"] = True
        router = SurveyRouter()
        result = _run_async(router.get_status(st.session_state.get("access_token", "")))
        if result.get("survey_completed"):
            st.session_state["survey_completed"] = True
            return True

    # 설문 UI 렌더링
    _render_survey()
    return False


def _render_survey():
    """설문 태그 선택 및 제출 UI를 렌더링합니다."""
    st.markdown("## 🌿 어떤 산책을 좋아하세요?")
    st.markdown("마음에 드는 키워드를 골라주세요! (여러 개 선택 가능)")

    # 태그 선택 (session_state로 선택 상태 유지)
    if "selected_tags" not in st.session_state:
        st.session_state["selected_tags"] = []

    cols = st.columns(3)
    for i, tag in enumerate(SURVEY_TAGS):
        with cols[i % 3]:
            selected = tag in st.session_state["selected_tags"]
            label = f"✅ {tag}" if selected else tag
            if st.button(label, key=f"tag_{tag}"):
                if selected:
                    st.session_state["selected_tags"].remove(tag)
                else:
                    st.session_state["selected_tags"].append(tag)
                st.rerun()

    st.markdown("---")
    st.markdown("**평소 산책 거리는 어느 정도인가요?**")
    distance_label = st.radio(
        "",
        ["~2km (가볍게)", "2~4km (적당히)", "4km+ (활발하게)"],
        index=1,
        horizontal=True,
        label_visibility="collapsed",
    )
    distance_map = {
        "~2km (가볍게)": "slow",
        "2~4km (적당히)": "normal",
        "4km+ (활발하게)": "fast",
    }
    distance = distance_map[distance_label]

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("완료", type="primary", use_container_width=True):
            router = SurveyRouter()
            _run_async(router.submit(
                st.session_state.get("access_token", ""),
                st.session_state["selected_tags"],
                distance,
            ))
            st.session_state["survey_completed"] = True
            st.session_state["selected_tags"] = []
            st.rerun()
    with col2:
        if st.button("나중에 하기", use_container_width=True):
            st.session_state["survey_completed"] = True
            st.rerun()
