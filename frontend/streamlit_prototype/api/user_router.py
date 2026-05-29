import httpx

from frontend.streamlit_prototype.api.base_url import base_url

class UserRouter:
    def __init__(self):
        self.base_url = f"{base_url}/api/user"

    async def post_user(self):
        """
        신규 사용자를 초기화하는 API를 호출합니다.
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{self.base_url}/init")
            return response.json()