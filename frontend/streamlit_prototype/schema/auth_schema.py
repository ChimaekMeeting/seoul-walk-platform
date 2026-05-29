from enum import Enum
from pydantic import BaseModel

class Status(Enum):
    """
    인증 처리 결과 상태를 나타내는 열거형입니다.
    """
    SUCCESS = "success"
    DUPLICATED_DISPLAY_ID = "duplicated_display_id"
    ACCESS_EXPIRED_TOKEN = "access_expired_token"
    REFRESH_EXPIRED_TOKEN = "refresh_expired_token"
    INVALID_TOKEN = "invalid_token"

class AuthResponse(BaseModel):
    """
    인증 요청에 대한 응답 스키마입니다.
    """
    status: Status