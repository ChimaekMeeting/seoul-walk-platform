import httpx

from frontend.streamlit_prototype.api.base_url import base_url


class UserRouter:
    def __init__(self):
        self.base_url = f"{base_url}/api/user"

    async def get_me(self, access_token: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            cookies = {"access_token": access_token} if access_token else {}
            response = await client.get(f"{self.base_url}/me", cookies=cookies)
            response.raise_for_status()
            return response.json()

    async def patch_me(self, access_token: str, nickname: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            cookies = {"access_token": access_token} if access_token else {}
            response = await client.patch(
                f"{self.base_url}/me",
                json={"nickname": nickname},
                cookies=cookies,
            )
            response.raise_for_status()
            return response.json()
