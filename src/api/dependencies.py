from fastapi import Depends
from src.service.login_service import KakaoLoginService
from src.service.user_service import UserService
from src.service.auth_service import AuthService

def get_auth_service() -> AuthService:
    return AuthService()

def get_user_service(
    service: AuthService = Depends(get_auth_service)
) -> UserService:
    return UserService(service)

def get_kakao_login_service(
    user_service: UserService = Depends(get_user_service),
    auth_service: AuthService = Depends(get_auth_service)
) -> KakaoLoginService:
    return KakaoLoginService(user_service, auth_service)