from pydantic import BaseModel
from typing import Optional
from enum import Enum

from src.schema.prewalk_schema import State


class InitRequest(BaseModel):
    """
    챗봇 세션 생성을 위한 입력 스키마
    """
    lat: float
    lon: float


class ChatRequest(BaseModel):
    """
    챗봇과 상호작용을 위한 입력 스키마
    """
    thread_id: str
    user_prompt: str


class ChatStatus(str, Enum):
    SUCCESS = "success"
    DUPLICATED_DISPLAY_ID = "duplicated_display_id"
    ACCESS_EXPIRED_TOKEN = "access_expired_token"
    REFRESH_EXPIRED_TOKEN = "refresh_expired_token"
    INVALID_TOKEN = "invalid_token"
    SESSION_NOT_FOUND = "session_not_found"  # 존재하지 않는 세션에 접근한 경우
    UNACCESSIBLE = "unaccessible"  # 다른 사람 세션에 접근한 경우


class ChatResponse(BaseModel):
    """
    챗봇과 상호작용을 통해 제공되는 출력 스키마
    """
    status: ChatStatus
    thread_id: Optional[str] = None
    state: Optional[State] = None