from uuid import uuid4
from src.repository.user_repository import UserRepository

class UserService:
    @staticmethod
    def save_and_get_uuid():
        """
        사용자의 uuid를 저장 후 반환합니다.
        """
        user_uuid = str(uuid4())
        UserRepository.save(user_uuid)
        return user_uuid