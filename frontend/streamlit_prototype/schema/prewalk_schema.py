from pydantic import BaseModel, Field

from src.schema.prewalk_schema import State


class InitRequest(BaseModel):
    """
    챗봇 세션 생성을 위한 입력 스키마입니다.
    """
    user_uuid: str
    lat: float
    lon: float


class ChatRequest(BaseModel):
    """
    챗봇과 상호작용을 위한 입력 스키마입니다.
    """
    thread_id: str
    user_prompt: str


class ChatResponse(BaseModel):
    """
    챗봇과 상호작용을 통해 제공되는 출력 스키마입니다.
    """
    thread_id: str
    state: State


class Weights(BaseModel):
    """
    산책 경로 생성을 위한 요소별 가중치 스키마입니다.
    """
    safety: float = Field(
        0.5,
        description="가로등/CCTV/안전/보안 지수",
        ge=0.0, le=1.0
    )
    nature: float = Field(
        0.5,
        description="공원/가로수길/상쾌함 지수",
        ge=0.0, le=1.0
    )
