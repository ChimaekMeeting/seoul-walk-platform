"""HTTP 요청에서 ROUDI access token을 일관되게 선택하는 공용 의존성."""

from fastapi import Cookie, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.interfaces.schema.auth_schema import Status


optional_access_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="AccessTokenBearer",
    description="ROUDI access token. refresh token은 인증 갱신 API의 Bearer 또는 로그아웃 본문으로 보냅니다.",
)


def resolve_access_token(
    request: Request,
    _credentials: HTTPAuthorizationCredentials | None = Depends(
        optional_access_bearer
    ),
    cookie_token: str | None = Cookie(
        default=None,
        alias="access_token",
        description="기존 웹 호출 호환용 ROUDI access token cookie",
    ),
) -> str | None:
    """Bearer를 우선하고, Authorization header가 없을 때만 cookie를 사용합니다."""
    authorization = request.headers.get("Authorization")
    if authorization is None:
        return cookie_token

    scheme, separator, token = authorization.partition(" ")
    token = token.strip()
    if (
        not separator
        or scheme.lower() != "bearer"
        or not token
        or any(character.isspace() for character in token)
    ):
        raise HTTPException(status_code=401, detail=Status.INVALID_TOKEN.value)
    return token
