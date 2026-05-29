import httpx

from frontend.streamlit_prototype.api.base_url import base_url

class AuthRouter:
    def __init__(self):
        self.base_url = f"{base_url}/api/auth"

    async def check_access_token(self, access_token: str):
        """
        access_token의 유효성을 검사하는 API를 호출합니다.
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            cookies = {"access_token": access_token}
            response = await client.get(f"{self.base_url}/check/access_token", cookies=cookies)
            return response.json()

    async def check_refresh_token(self, refresh_token: str):
        """
        refresh_token을 이용하여 access_token을 재발급하는 API를 호출합니다.
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            cookies = {"refresh_token": refresh_token}
            response = await client.get(f"{self.base_url}/check/refresh_token", cookies=cookies)
            new_access_token = response.cookies.get("access_token")
            return response.json(), new_access_token
