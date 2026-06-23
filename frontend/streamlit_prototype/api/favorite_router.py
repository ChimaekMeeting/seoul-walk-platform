import httpx

from frontend.streamlit_prototype.api.base_url import base_url


class FavoriteRouter:
    def __init__(self):
        self.base_url = f"{base_url}/api/user"

    async def toggle_favorite(self, access_token: str, history_id: int) -> dict:
        cookies = {"access_token": access_token} if access_token else {}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.patch(
                f"{self.base_url}/routes/{history_id}/favorite",
                cookies=cookies,
            )
            response.raise_for_status()
            return response.json()
