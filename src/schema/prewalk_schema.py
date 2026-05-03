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

class Location(BaseModel):
    """
    위치(출발지, 목적지) 관련 스키마
    """
    lat: Optional[float] = Field(None, description="위도(Latitude)")
    lon: Optional[float] = Field(None, description="경도(Longitude)")
    address: Optional[str] = Field(None, description="지번 주소 또는 도로명 주소")
    place_name: Optional[str] = Field(None, description="장소 명칭")

class UserPreferenceContext(BaseModel):
    """
    산책 경로 추천을 위해 꼭 필요한 스키마
    """
    is_circular: Optional[bool] = Field(None, description="순환/원점회귀 여부")
    origin: Optional[Location] = Field(None, description="출발지 정보 (좌표 포함)")
    destination: Optional[Location] = Field(None, description="목적지 정보 (좌표 포함)")
    purpose: Optional[str] = Field(None, description="산책 목적")
    distance_km: Optional[float] = Field(None, description="산책 거리(km)")

class Weights(BaseModel):
    """
    산책 경로 생성을 위한 요소별 가중치 스키마
    모든 가중치의 합은 1.0(100%)이 되는 것을 권장합니다.
    """
    safety: float = Field(
        0.0, 
        description="가로등/CCTV 보안 지수", 
        ge=0.0, le=1.0  # ge(Greater than or Equal to), le(Less than or Equal to)
    )
    nature: float = Field(
        0.0, 
        description="공원/가로수길 지수", 
        ge=0.0, le=1.0
    )