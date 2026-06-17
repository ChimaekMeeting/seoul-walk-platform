from pydantic import BaseModel, Field
from typing import Optional, Union, List, Literal
from src.infrastructure.external.schema.weather_schema import EnvironmentInfo


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
    origin: Optional[Location] = Field(None, description="출발지 정보")
    purpose: Optional[str] = Field(None, description="산책 목적")
    
    # 챗봇에서 추출한 사용자 선호를 route_engine.profiles.py와 연결하기 위한 필드
    profile_name: str = Field(
        "default", 
        description="route_engine.profiles.py와 매핑되는 프로필명 (default, quiet, flat, safe, scenic, child, running)"
    )
    child_friendly: bool = Field(False, description="어린이 동반, 유모차 등 안전 우선 모드 여부")
    
    # 현재 시스템(route_engine/DB)에서 직접 지원하지 않는 조건(예: 그늘, 시원함)을 
    # 유실하지 않고 기록하기 위한 보존용 필드
    unsupported_preferences: list[str] = Field(
        default_factory=list, 
        description="현재 매핑 불가능한 사용자 요구사항 보존"
    )


class CircularPreference(BasePreference):
    """
    순환 산책 모드 선택 시, 산책 경로 추천을 위해 필요한 정보 관련 스키마
    """
    mode: Literal["Circular"] = "Circular"


class DestinationPreference(BasePreference):
    """
    '목적지'가 정해져 있는 산책 모드 선택 시, 산책 경로 추천을 위해 필요한 정보 관련 스키마
    """
    mode: Literal["Destination"] = "Destination"
    destination: Optional[Location] = Field(None, description="목적지 정보")


class DistancePreference(BasePreference):
    """
    '거리'가 정해져 있는 산책 모드 선택 시, 산책 경로 추천을 위해 필요한 정보 관련 스키마
    """
    mode: Literal["Distance"] = "Distance"
    distance_km: Optional[float] = Field(None, description="산책 거리(km)")


class WalkPreferenceExtraction(BaseModel):
    """
    사용자의 의도를 분석하여 선택된 산책 모드 정보
    """
    preference: Union[CircularPreference, DestinationPreference, DistancePreference] = Field(
        ..., discriminator="mode"
    )


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

    weather_data: Optional[EnvironmentInfo] = None
    user_prompt: str = ""
    next_node: str = "interviewer"
