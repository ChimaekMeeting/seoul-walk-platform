from fastapi import APIRouter, Body, Depends, Query, Request, Response
from src.service.user.login_service import KakaoLoginService
from src.interfaces.schema.login_schema import LoginUrlResponse, LoginResponse, MobileLoginRequest
from src.interfaces.schema.auth_schema import AuthResponse, Status
from src.interfaces.dependencies import get_kakao_login_service

router = APIRouter(
    prefix="/api/login",
    tags=["Login"]
)

@router.get("/kakao", response_model=LoginUrlResponse)
def get_kakao_login_url(
    service: KakaoLoginService = Depends(get_kakao_login_service)
):
    """
    카카오 OAuth 로그인 페이지 URL을 반환합니다.
    """
    url = service.get_login_url()
    return LoginUrlResponse(url=url)

@router.get("/kakao/callback", response_model=LoginResponse)
async def kakao_callback(
    response: Response,
    code: str = Query(..., description="카카오 OAuth 인가 코드"),
    service: KakaoLoginService = Depends(get_kakao_login_service)
):
    """
    카카오 인가 코드로 로그인을 처리합니다 (웹/Streamlit OAuth 리다이렉트 흐름).
    """
    jwt_access_token, refresh_token, nickname = await service.login(code)

    response.set_cookie(
        key="access_token",
        value=jwt_access_token,
        httponly=True,
        secure=False,  # 배포 시에는 True로 설정하여 HTTPS 환경에서만 전송되도록 수정
        samesite="lax",
        max_age=3600   # 1시간
    )

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=False,  # stx.CookieManager가 JS로 읽어야 하므로 False
        secure=False,
        samesite="lax",
        max_age=14 * 24 * 60 * 60
    )
    return LoginResponse(status=Status.SUCCESS, token_type="Bearer", nickname=nickname, access_token=jwt_access_token, refresh_token=refresh_token)

@router.post("/kakao/mobile-login", response_model=LoginResponse)
async def kakao_mobile_login(
    body: MobileLoginRequest,
    service: KakaoLoginService = Depends(get_kakao_login_service)
):
    """
    카카오 액세스 토큰으로 로그인합니다 (RN 앱 전용).
    @react-native-seoul/kakao-login SDK가 발급한 액세스 토큰을 body로 받습니다.
    """
    jwt_access_token, refresh_token, nickname = await service.login_with_access_token(body.access_token)
    return LoginResponse(status=Status.SUCCESS, token_type="Bearer", nickname=nickname, access_token=jwt_access_token, refresh_token=refresh_token)

@router.post("/kakao/logout", response_model=AuthResponse)
async def kakao_logout(
    request: Request,
    response: Response,
    service: KakaoLoginService = Depends(get_kakao_login_service)
):
    access_token = request.cookies.get("access_token")
    refresh_token = request.cookies.get("refresh_token")

    await service.logout(access_token, refresh_token)

    response.delete_cookie(key="access_token")
    response.delete_cookie(key="refresh_token")

    return AuthResponse(status=Status.SUCCESS)