from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

class Status(str, Enum):
    SUCCESS = "success"
    ACCESS_EXPIRED_TOKEN = "access_expired_token"
    REFRESH_EXPIRED_TOKEN = "refresh_expired_token"
    INVALID_TOKEN = "invalid_token"

class AuthResponse(BaseModel):
    status: Status = Field(description="인증 처리 결과. 일부 인증 실패도 HTTP 200의 status로 구분합니다.")
    access_token: Optional[str] = Field(
        default=None,
        description="refresh 성공 시에만 반환하는 새 ROUDI access token",
    )
