from uuid import uuid4

from src.repository.user_repository import UserRepository
from src.entity.user import User
from src.service.auth_service import AuthService

class UserService:
    def __init__(self, auth_service: AuthService):
        self.auth_service = auth_service

    def save_and_get_uuid(self):
        """
        사용자의 uuid를 저장 후 반환합니다.
        """
        user_uuid = str(uuid4())
        UserRepository.save(user_uuid)
        return user_uuid
    
    # def login(
    #     self,
    #     provider_id: int,
    #     refresh_token: str,
    #     nickname: str
    # ) -> User:
    #     """
    #     DB에 회원정보가 없으면 저장을, 회원정보가 있다면, refresh_token을 업데이트합니다.
    #     """
    #     user = UserRepository.find_by_provider_id(provider_id)

    #     if user is not None:
    #         return UserRepository.update(user.provider_id, refresh_token)
        
    #     return UserRepository.save(provider_id, refresh_token, nickname)