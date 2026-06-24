"""
frontend/streamlit_prototype/api/banner_router.py

GET /api/banner HTTP 클라이언트 래퍼
위치 좌표를 전달해 배너 목록을 동기 방식으로 조회
"""
import httpx
from frontend.streamlit_prototype.api.base_url import base_url


class BannerRouter:
    def __init__(self):
        self.base_url = f"{base_url}/api/banner"

    def get_banner_list(self, lat: float, lon: float, hour: int | None = None) -> list:
        """
        input : lat (float), lon (float), hour (선택)
        output: [{"emoji", "text", "sub", ...}, ...] 또는 실패 시 []

        GET /api/banner 호출 후 배너 목록 반환
        """
        try:
            params = {"lat": lat, "lon": lon}
            if hour is not None:
                params["hour"] = hour
            data = httpx.get(self.base_url, params=params, timeout=10.0).json()
            return data.get("items", [])
        except Exception:
            return []
