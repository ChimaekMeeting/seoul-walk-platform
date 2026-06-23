"""
frontend/streamlit_prototype/api/map_router.py

지도 레이어 데이터 HTTP 클라이언트 래퍼
카카오 시설, DB 포인트, DB 엣지 3가지 엔드포인트를 동기 방식으로 호출
"""
import httpx
from frontend.streamlit_prototype.api.base_url import base_url


class MapRouter:
    def __init__(self):
        self.base_url = f"{base_url}/api/map"

    def get_facilities(self, lat, lon, category_code=None, keyword=None, radius=2000) -> list:
        """
        input : lat, lon, category_code, keyword, radius
        output: [{"name", "lon", "lat", "address"}, ...] 또는 실패 시 []

        GET /api/map/facilities 호출
        """
        try:
            params = {"lat": lat, "lon": lon, "radius": radius}
            if category_code:
                params["category_code"] = category_code
            if keyword:
                params["keyword"] = keyword
            return httpx.get(f"{self.base_url}/facilities", params=params, timeout=10.0).json()
        except Exception:
            return []

    def get_points(self, lat, lon, layer, radius_m=2000) -> list:
        """
        input : lat, lon, layer(safety/nature/landmark), radius_m
        output: [{"lat", "lon", "category"?}, ...] 또는 실패 시 []

        GET /api/map/points/{layer} 호출 (레이어 전체 반환, 카테고리 필터는 호출측에서)
        """
        try:
            params = {"lat": lat, "lon": lon, "radius_m": radius_m}
            return httpx.get(f"{self.base_url}/points/{layer}", params=params, timeout=10.0).json()
        except Exception:
            return []

    def get_edges(self, lat, lon, radius_m=2000) -> list:
        """
        input : lat, lon, radius_m
        output: [{"path": [[lon, lat], ...], "link_id": str}, ...] 또는 실패 시 []

        GET /api/map/edges 호출
        """
        try:
            return httpx.get(
                f"{self.base_url}/edges",
                params={"lat": lat, "lon": lon, "radius_m": radius_m},
                timeout=10.0,
            ).json()
        except Exception:
            return []
