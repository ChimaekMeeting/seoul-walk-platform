from pydantic import BaseModel

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


class ChatResponse(BaseModel):
    """
    챗봇과 상호작용을 통해 제공되는 출력 스키마
    """
    thread_id: str
    state: State