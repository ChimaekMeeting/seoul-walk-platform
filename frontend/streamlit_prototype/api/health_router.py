"""
frontend/streamlit_prototype/api/health_router.py

GET /api/health HTTP 클라이언트 래퍼
FastAPI 서버의 DB 연결 상태 확인 엔드포인트를 동기 방식으로 호출
"""
import httpx
import streamlit as st

from frontend.streamlit_prototype.api.base_url import base_url


@st.cache_data(ttl=30)
def _fetch_health(url: str) -> bool:
    """GET /api/health를 30초 캐싱하여 ok 필드를 반환합니다."""
    try:
        response = httpx.get(url, timeout=3.0)
        return response.json().get("ok", False)
    except Exception:
        return False


class HealthRouter:
    def __init__(self):
        self.base_url = f"{base_url}/api/health"

    def get_health(self) -> bool:
        """
        input : 없음
        output: bool (DB 연결 정상이면 True, 실패 또는 서버 오류 시 False)

        GET /api/health 결과를 30초 캐싱하여 반환 (rerun마다 재호출 방지)
        """
        return _fetch_health(self.base_url)
