import httpx

from frontend.streamlit_prototype.api.base_url import base_url


class UserRouter:
    def __init__(self):
        self.base_url = f"{base_url}/api/user"

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
