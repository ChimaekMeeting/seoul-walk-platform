from fastapi import APIRouter, Depends, Cookie, Response

from src.api.dependencies import get_auth_service
from src.service.auth_service import AuthService
from src.schema.auth_schema import AuthResponse

router = APIRouter(
    prefix="/api/auth",
    tags=["Auth"]
)

@router.get("/check/access_token", response_model=AuthResponse)
def check_access_token(
    access_token: str = Cookie(None),
    service: AuthService = Depends(get_auth_service)
):
    status, _ = service.check_access_token(access_token)
    return AuthResponse(status=status)

@router.get("/check/refresh_token", response_model=AuthResponse)
def check_refresh_token(
    response: Response,
    refresh_token: str = Cookie(None),
    service: AuthService = Depends(get_auth_service)
):
    status, access_token, _ = service.check_refresh_token(refresh_token)

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=False,  # 배포 시에는 True로 설정하여 HTTPS 환경에서만 전송되도록 수정
        samesite="lax",
        max_age=3600   # 1시간
    )

    return AuthResponse(status=status)