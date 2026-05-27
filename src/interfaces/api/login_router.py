from fastapi import APIRouter, Depends, Query, Request, Response
from src.service.login_service import KakaoLoginService
from src.schema.login_schema import LoginUrlResponse, LoginResponse
from src.schema.auth_schema import AuthResponse, Status
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
    code: str = Query(...),
    service: KakaoLoginService = Depends(get_kakao_login_service)
):
    """
    카카오 인가 코드로 로그인을 처리하고 access/refresh 토큰을 쿠키에 저장합니다.
    """
    access_token, refresh_token, nickname, display_id = await service.login(code)

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=False,  # 배포 시에는 True로 설정하여 HTTPS 환경에서만 전송되도록 수정
        samesite="lax",
        max_age=3600   # 1시간
    )

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=14 * 24 * 60 * 60  # 14일
    )

    return LoginResponse(status=Status.SUCCESS, token_type="Bearer", nickname=nickname, display_id=display_id)

# @router.post("/kakao/logout", response_model=AuthResponse)
# async def kakao_logout(
#     request: Request,
#     response: Response,
#     service: KakaoLoginService = Depends(get_kakao_login_service)
# ):
#     access_token = request.cookies.get("access_token")
#     refresh_token = request.cookies.get("refresh_token")

#     service.logout(access_token, refresh_token)

#     response.delete_cookie(key="access_token")
#     response.delete_cookie(key="refresh_token")

#     return AuthResponse(status=Status.SUCCESS)