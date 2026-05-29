import httpx

from frontend.streamlit_prototype.api.base_url import base_url

class LoginRouter:
    def __init__(self):
        self.base_url = f"{base_url}/api/login"

    async def get_kakao_login_url(self):
        """
        카카오 로그인 URL을 조회하는 API를 호출합니다.
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(f"{self.base_url}/kakao")
            return response.json()

    async def kakao_callback(self, code: str):
        """
        카카오 로그인 콜백을 처리하고 access_token 및 refresh_token을 반환하는 API를 호출합니다.
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            params = {"code": code}
            response = await client.get(f"{self.base_url}/kakao/callback", params=params)
            access_token = response.cookies.get("access_token")
            refresh_token = response.cookies.get("refresh_token")
            return response.json(), access_token, refresh_token
