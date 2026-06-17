"""
frontend/streamlit_prototype/api/health_router.py

GET /api/health HTTP 클라이언트 래퍼
FastAPI 서버의 DB 연결 상태 확인 엔드포인트를 동기 방식으로 호출
"""
import httpx
from frontend.streamlit_prototype.api.base_url import base_url


class HealthRouter:
    def __init__(self):
        self.base_url = f"{base_url}/api/health"

    def get_health(self) -> bool:
        """
        input : 없음
        output: bool (DB 연결 정상이면 True, 실패 또는 서버 오류 시 False)

        GET /api/health를 동기 호출해 ok 필드를 반환
        요청 실패 시 False 반환
        """
        try:
            response = httpx.get(self.base_url, timeout=3.0)
            return response.json().get("ok", False)
        except Exception:
            return False
