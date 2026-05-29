from pydantic import BaseModel
from typing import Optional

from src.interfaces.schema.auth_schema import Status

class UuidResponse(BaseModel):
    """
    신규 사용자에게 고유 식별자(UUID)를 제공하는 모델입니다.
    """
    user_uuid: str

class UserResponse(BaseModel):
    """
    로그인 또는 인증 후 사용자 정보를 담는 응답 스키마입니다.
    """
    status: Status
    nickname: Optional[str] = None
    display_id: Optional[str] = None