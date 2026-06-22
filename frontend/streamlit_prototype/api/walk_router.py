import httpx

from frontend.streamlit_prototype.api.base_url import base_url


class WalkRouter:
    def __init__(self):
        self.base_url = f"{base_url}/api/walk/route"

    async def post_route(self, access_token: str, payload: dict) -> dict:
        """
        산책 경로 추천 API를 호출합니다.
        access_token은 쿠키로 전송되어 로그인 여부를 검증합니다.
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            cookies = {"access_token": access_token} if access_token else {}
            response = await client.post(self.base_url, json=payload, cookies=cookies)
            return response.json()
