"""
frontend/streamlit_prototype/api/survey_router.py

온보딩 설문 관련 백엔드 API 호출 클라이언트.
"""
import httpx
from frontend.streamlit_prototype.api.base_url import base_url


class SurveyRouter:
    """설문 제출 및 완료 여부 조회 API 클라이언트."""

    def __init__(self):
        self.base_url = f"{base_url}/api/user"

    async def get_status(self, access_token: str) -> dict:
        """GET /api/user/survey — 설문 완료 여부를 조회합니다."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            cookies = {"access_token": access_token} if access_token else {}
            response = await client.get(f"{self.base_url}/survey", cookies=cookies)
            if response.status_code != 200:
                return {"survey_completed": False}
            return response.json()

    async def submit(self, access_token: str, tags: list[str], distance: str | None) -> dict:
        """POST /api/user/survey — 설문 결과를 제출합니다."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            cookies = {"access_token": access_token} if access_token else {}
            response = await client.post(
                f"{self.base_url}/survey",
                json={"tags": tags, "distance": distance},
                cookies=cookies,
            )
            return response.json()
