from pydantic import BaseModel, Field
from typing import Optional, Union, List
from enum import Enum

class InitRequest(BaseModel):
    """
    챗봇 세션 생성을 위한 입력 스키마
    """
    user_uuid: str  # 추후 실제 id(<-SNS 로그인)로 바꿀 예정
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
    message: str
    state: dict

class PathMode(Enum):
    """
    산책 모드 관련 Enum class
    """
    CIRCULAR = "Circular"        # 순환 산책
    DESTINATION = "Destination"  # '목적지'가 정해져 있는 편도 산책
    DISTANCE = "Distance"        # '거리(km)'가 정해져 있는 편도 산책

class Location(BaseModel):
    """
    위치(출발지, 목적지) 관련 스키마
    """
    lat: Optional[float] = Field(None, description="위도(Latitude)")
    lon: Optional[float] = Field(None, description="경도(Longitude)")
    address: Optional[str] = Field(None, description="지번 주소 또는 도로명 주소")
    place_name: Optional[str] = Field(None, description="장소 명칭")

class BasePreference(BaseModel):
    """
    산책 경로 추천을 위해 필요한 기본 정보 관련 스키마
    """
    origin: Optional[Location] = Field(None, description = "")
    purpose: Optional[str] = Field(None, description="")

class CircularPreference(BasePreference):
    """
    순환 산책 모드 선택 시, 산책 경로 추천을 위해 필요한 정보 관련 스키마
    """
    pass

class DestinationPreference(BasePreference):
    """
    '목적지'가 정해져 있는 산책 모드 선택 시, 산책 경로 추천을 위해 필요한 정보 관련 스키마
    """
    destination: Optional[Location] = Field(None, description="목적지 정보 (좌표 포함)")

class DistancePreference(BasePreference):
    """
    '거리'가 정해져 있는 산책 모드 선택 시, 산책 경로 추천을 위해 필요한 정보 관련 스키마
    """
    distance_km: Optional[float] = Field(None, description="산책 거리(km)")

class State(BaseModel):
    """
    대화 상태 관련 스키마
    """
    user_uuid: str
    current_location: Location

    user_context: Optional[
        Union[CircularPreference, DestinationPreference, DistancePreference]
    ] = None

    origin_candidate: Optional[List[Location]] = None
    destination_candidate: Optional[List[Location]] = None

    weather_data: dict = {}
    user_prompt: str = ""
    next_node: str = "interviewer"  # interviewer or end

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