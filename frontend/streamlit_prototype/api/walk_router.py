import httpx

from frontend.streamlit_prototype.api.base_url import base_url


class WalkRouter:
    def __init__(self):
        self.base_url = f"{base_url}/api/walk/route"

    async def post_route(self, payload: dict) -> dict:
        """산책 경로 추천 API를 호출합니다."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(self.base_url, json=payload)
            response.raise_for_status()
            return response.json()
