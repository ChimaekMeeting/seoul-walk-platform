import httpx

from frontend.streamlit_prototype.api.base_url import base_url

class PrewalkRouter:
    def __init__(self):
        self.base_url = f"{base_url}/api/prewalk"

    async def post_init(self, access_token: str, lat: float, lon: float):
        """
        현재 위치(위도, 경도)를 기반으로 산책 세션을 초기화하는 API를 호출합니다.
        access_token은 쿠키로 전송되어 사용자를 식별합니다.
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            cookies = {"access_token": access_token} if access_token else {}
            body = {
                "lat": lat,
                "lon": lon
            }
            response = await client.post(f"{self.base_url}/init", json=body, cookies=cookies)
            return response.json()

    async def post_intent(self, access_token: str, thread_id: str, user_prompt: str):
        """
        thread_id와 사용자 프롬프트를 기반으로 산책 의도를 분석하는 API를 호출합니다.
        access_token은 쿠키로 전송되어 세션 소유권을 검증합니다.
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            cookies = {"access_token": access_token} if access_token else {}
            body = {
                "thread_id": thread_id,
                "user_prompt": user_prompt
            }
            response = await client.post(f"{self.base_url}/intent", json=body, cookies=cookies)
            try:
                return response.json()
            except Exception:
                return {"status": "internal_error", "detail": response.text}
