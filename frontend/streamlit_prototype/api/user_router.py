import httpx

from frontend.streamlit_prototype.api.base_url import base_url


class UserRouter:
    def __init__(self):
        self.base_url = f"{base_url}/api/user"

    async def get_me(self, access_token: str) -> dict:
        cookies = {"access_token": access_token} if access_token else {}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self.base_url}/me", cookies=cookies)
            response.raise_for_status()
            return response.json()

    async def patch_me(self, access_token: str, nickname: str) -> dict:
        cookies = {"access_token": access_token} if access_token else {}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.patch(
                f"{self.base_url}/me",
                json={"nickname": nickname},
                cookies=cookies,
            )
            response.raise_for_status()
            return response.json()

    async def get_route_histories(self, access_token: str, limit: int = 20, offset: int = 0) -> dict:
        cookies = {"access_token": access_token} if access_token else {}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{self.base_url}/routes",
                params={"limit": limit, "offset": offset},
                cookies=cookies,
            )
            response.raise_for_status()
            return response.json()

    async def get_routes(self, access_token: str, limit: int = 20, offset: int = 0) -> dict:
        """GET /api/user/routes — 경로 기록 목록을 조회합니다."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            cookies = {"access_token": access_token} if access_token else {}
            response = await client.get(
                f"{self.base_url}/routes",
                params={"limit": limit, "offset": offset},
                cookies=cookies,
            )
            response.raise_for_status()
            return response.json()

    async def toggle_favorite(self, access_token: str, history_id: int) -> dict:
        """PATCH /api/user/routes/{history_id}/favorite — 즐겨찾기를 토글합니다."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            cookies = {"access_token": access_token} if access_token else {}
            response = await client.patch(
                f"{self.base_url}/routes/{history_id}/favorite",
                cookies=cookies,
            )
            response.raise_for_status()
            return response.json()
