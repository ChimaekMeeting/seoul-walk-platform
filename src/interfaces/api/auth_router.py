from fastapi import APIRouter, Depends, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.interfaces.dependencies import get_auth_service
from src.service.user.auth_service import AuthService
from src.interfaces.schema.auth_schema import AuthResponse, Status

router = APIRouter(
    prefix="/api/auth",
    tags=["Auth"]
)

optional_bearer = HTTPBearer(auto_error=False)

@router.get("/check/access_token", response_model=AuthResponse)
def check_access_token(
    credentials: HTTPAuthorizationCredentials = Depends(optional_bearer),
    service: AuthService = Depends(get_auth_service)
):
    """
    Authorization 헤더의 Bearer access_token 유효성을 검사합니다.
    """
    access_token = credentials.credentials if credentials else None
    status, _, _ = service.check_access_token(access_token)
    return AuthResponse(status=status)

@router.get("/check/refresh_token", response_model=AuthResponse)
async def check_refresh_token(
    response: Response,
    credentials: HTTPAuthorizationCredentials = Depends(optional_bearer),
    service: AuthService = Depends(get_auth_service)
):
    """
    Authorization 헤더의 Bearer refresh_token으로 access_token을 재발급하고 쿠키에 저장합니다.
    """
    refresh_token = credentials.credentials if credentials else None
    status, access_token, _ = await service.check_refresh_token(refresh_token)

    # 재발급 성공 시에만 새 access_token을 쿠키에 저장합니다.
    if status == Status.SUCCESS:
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=False,
            secure=False,  # 배포 시에는 True로 설정하여 HTTPS 환경에서만 전송되도록 수정
            samesite="lax",
            max_age=3600   # 1시간
        )

    # 쿠키를 사용할 수 없는 RN 앱을 위해 body에도 access_token을 포함합니다.
    return AuthResponse(status=status, access_token=access_token if status == Status.SUCCESS else None)