from fastapi import APIRouter, Depends, Query
from src.service.user_service import UserService, KakaoLoginService
from src.schema.user_schema import (
    UuidResponse,
    KakaoLoginUrlResponse,
    KakaoLoginResponse,
    KakaoLogoutRequest,
    KakaoLogoutResponse,
    KakaoTokenRefreshRequest,
)

router = APIRouter(
    prefix="/api",
    tags=["user"]
)

# 싱글톤 인스턴스
kakao_login_service = KakaoLoginService()

#서비스 인스턴스를 관리하는 함수(의존성 주입용)
def get_kakao_login_service() -> KakaoLoginService:
    return kakao_login_service

@router.post("/init", response_model=UuidResponse)
def read_init():
    """
    서비스에 처음 방문한 유저에게 uuid를 제공합니다.
    """
    user_uuid = UserService.save_and_get_uuid()
    return UuidResponse(user_uuid=user_uuid)

@router.get("/login/kakao/get_url", response_model=KakaoLoginUrlResponse)
def read_kakao_login_url(
    service: KakaoLoginService = Depends(get_kakao_login_service)
):
    """
    카카오 로그인 url을 제공합니다.
    """
    return service.get_url()

@router.get("/login/kakao/callback", response_model=KakaoLoginResponse)
async def kakao_login(
    code: str = Query(...),
    service: KakaoLoginService = Depends(get_kakao_login_service)
):
    """
    카카오 로그인을 통해 서비스 JWT와 닉네임을 반환합니다.
    """
    return await service.login(code)

@router.post("/login/kakao/refresh", response_model=KakaoLoginResponse)
async def kakao_token_refresh(
    request: KakaoTokenRefreshRequest,
    service: KakaoLoginService = Depends(get_kakao_login_service)
):
    """
    카카오 refresh_token으로 새 서비스 JWT를 발급합니다.
    """
    return await service.refresh_kakao_token(request.kakao_refresh_token)

@router.post("/logout/kakao", response_model=KakaoLogoutResponse)
async def kakao_logout(
    request: KakaoLogoutRequest,
    service: KakaoLoginService = Depends(get_kakao_login_service)
):
    """
    카카오 로그아웃을 수행합니다.
    """
    await service.logout(request.kakao_access_token)
    return KakaoLogoutResponse(message="로그아웃 성공")