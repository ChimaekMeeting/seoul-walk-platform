from src.infrastructure.cache.valkey import get_valkey_db
from src.entity.user import Provider

class UserRepository:
    @staticmethod
    async def save_refresh_token(provider: Provider, provider_id: str, refresh_token: str, expires_in_seconds: int = 1209600) -> None:
        """
        사용자의 refresh token을 14일 동안 Valkey에 저장합니다.
        """
        redis = get_valkey_db()
        key = f"refresh_token:{provider.value}:{provider_id}"

        await redis.set(key, refresh_token, expires_in_seconds)

    @staticmethod
    async def get_refresh_token(provider: Provider, provider_id: str) -> str:
        """
        사용자의 refresh token을 조회합니다.
        """
        redis = get_valkey_db()
        key = f"refresh_token:{provider.value}:{provider_id}"

        return await redis.get(key)

    @staticmethod
    async def delete_refresh_token(provider: Provider, provider_id: str):
        """
        사용자의 refresh token을 삭제합니다.
        """
        redis = get_valkey_db()
        key = f"refresh_token:{provider.value}:{provider_id}"

        await redis.delete(key)
