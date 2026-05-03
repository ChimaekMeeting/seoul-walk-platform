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

class Location(BaseModel):
    lat: Optional[float] = Field(None, description="위도(Latitude)")
    lon: Optional[float] = Field(None, description="경도(Longitude)")
    address: Optional[str] = Field(None, description="지번 주소 또는 도로명 주소")
    place_name: Optional[str] = Field(..., description="장소 명칭")

class UserPreferenceContext(BaseModel):
    is_circular: Optional[bool] = Field(None, description="순환/원점회귀 여부")
    origin: Optional[Location] = Field(None, description="출발지 정보 (좌표 포함)")
    destination: Optional[Location] = Field(None, description="목적지 정보 (좌표 포함)")
    purpose: Optional[str] = Field(None, description="산책 목적")
    distance_km: Optional[float] = Field(None, description="산책 거리(km)")