import httpx

from frontend.streamlit_prototype.api.base_url import base_url

class PrewalkAPITester:
    def __init__(self):
        self.base_url = f"{base_url}/api/prewalk"

    async def post_init(self, user_uuid: str, lat: float, lon: float):
        """
        사용자 UUID와 현재 위치(위도, 경도)를 기반으로 산책 세션을 초기화하는 API를 호출합니다.
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            params = {
                "user_uuid": user_uuid,
                "lat": lat,
                "lon": lon
            }
            response = await client.post(f"{self.base_url}/init", json=params)
            return response.json()

    async def post_intent(self, thread_id: str, user_prompt: str):
        """
        thread_id와 사용자 프롬프트를 기반으로 산책 의도를 분석하는 API를 호출합니다.
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            params = {
                "thread_id": thread_id,
                "user_prompt": user_prompt
            }
            response = await client.post(f"{self.base_url}/intent", json=params)
            return response.json()

    async def get_weights(self, thread_id: str):
        """
        thread_id에 해당하는 경로 가중치를 조회하는 API를 호출합니다.
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            params = {
                "thread_id": thread_id
            }
            response = await client.get(f"{self.base_url}/weights", params=params)
            return response.json()