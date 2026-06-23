from src.repository.user.user_repository import UserRepository
from src.repository.user.user_preference_repository import UserPreferenceRepository
from src.infrastructure.cache.repository.user_repository import UserRepository as CacheUserRepository
from src.entity.user import User, Provider
from src.service.user.auth_service import AuthService
from src.interfaces.schema.auth_schema import Status
from src.interfaces.schema.user_schema import UserMeResponse, UserUpdateResponse, UserStatus


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

    def get_me(self, access_token: str | None) -> UserMeResponse:
        """
        로그인한 사용자의 닉네임과 설문 완료 여부를 반환합니다.
        """
        status, provider, provider_id = self.auth_service.check_access_token(access_token)
        if status != Status.SUCCESS:
            return UserMeResponse(status=UserStatus(status.value))

        user = UserRepository.find_by_provider_and_provider_id(provider, provider_id)
        if user is None:
            return UserMeResponse(status=UserStatus.USER_NOT_FOUND)

        survey_completed = UserPreferenceRepository.find_survey_completed(user.id)

        return UserMeResponse(
            status=UserStatus.SUCCESS,
            nickname=user.nickname,
            survey_completed=survey_completed,
        )

    def update_me(self, access_token: str | None, nickname: str) -> UserUpdateResponse:
        """
        로그인한 사용자의 닉네임을 수정합니다.
        """
        status, provider, provider_id = self.auth_service.check_access_token(access_token)
        if status != Status.SUCCESS:
            return UserUpdateResponse(status=UserStatus(status.value))

        user = UserRepository.update_nickname(provider, provider_id, nickname)
        if user is None:
            return UserUpdateResponse(status=UserStatus.USER_NOT_FOUND)

        return UserUpdateResponse(
            status=UserStatus.SUCCESS,
            nickname=user.nickname,
        )
