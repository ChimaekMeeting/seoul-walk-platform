"""
frontend/streamlit_prototype/api/banner_router.py

GET /api/banner HTTP 클라이언트 래퍼
날씨 상태와 시각을 전달해 배너 목록을 동기 방식으로 조회
"""
import httpx
from frontend.streamlit_prototype.api.base_url import base_url


class BannerRouter:
    def __init__(self):
        self.base_url = f"{base_url}/api/banner"

    def get_banner_list(self, weather_status: str, weather_msg: str, hour: int | None = None) -> list:
        """
        input : weather_status, weather_msg, hour (선택)
        output: [{"emoji", "text", "sub", ...}, ...] 또는 실패 시 []

        GET /api/banner 호출 후 배너 목록 반환
        """
        try:
            params = {"weather_status": weather_status, "weather_msg": weather_msg}
            if hour is not None:
                params["hour"] = hour
            return httpx.get(self.base_url, params=params, timeout=10.0).json()
        except Exception:
            return []
