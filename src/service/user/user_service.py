from uuid import uuid4

from src.repository.user.user_repository import UserRepository
from src.infrastructure.cache.repository.user_repository import UserRepository as CacheUserRepository
from src.entity.user import User, Provider
from src.service.user.auth_service import AuthService

class UserService:
    def __init__(self, auth_service: AuthService):
        self.auth_service = auth_service
    
    async def save(
        self,
        provider: Provider,
        provider_id: str,
        refresh_token: str,
        nickname: str
    ) -> User:
        """
        DB에 회원정보가 없으면 저장을, 회원정보가 있다면, refresh_token을 업데이트합니다.
        """
        user = UserRepository.find_by_provider_and_provider_id(provider, provider_id)
        await CacheUserRepository.save_refresh_token(provider, provider_id, refresh_token)
        
        if user is None:
            return UserRepository.save(provider, provider_id, nickname)