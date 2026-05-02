from pydantic import BaseModel, Field
from typing import Optional

class InitRequest(BaseModel):
    user_uuid: str
    lat: float
    lon: float

class ChatRequest(BaseModel):
    thread_id: str
    user_prompt: str

class ChatResponse(BaseModel):
    thread_id: str
    message: str
    state: dict
    weights: Optional[dict] = None

class UserPreferenceContext(BaseModel):
    is_circular: Optional[bool] = Field(None, description="순환/원점회귀 여부")
    origin: Optional[str] = Field(None, description="출발지")
    destination: Optional[str] = Field(None, description="목적지")
    purpose: Optional[str] = Field(None, description="산책 목적")
    distance_km: Optional[float] = Field(None, description="산책 거리(km)")