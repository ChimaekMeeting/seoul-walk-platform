from pydantic import BaseModel, Field
from typing import Optional, Union, List
from src.infrastructure.external.schema.weather_schema import EnvironmentInfo
from src.interfaces.schema.walk_schema import OnewayMode, CircularMode, WalkRouteResponse


class Location(BaseModel):
    """
    위치(출발지, 목적지) 관련 정보입니다.
    """
    lat: Optional[float] = Field(None, description="위도(Latitude)")
    lon: Optional[float] = Field(None, description="경도(Longitude)")
    address: Optional[str] = Field(None, description="지번 주소 또는 도로명 주소")
    place_name: Optional[str] = Field(None, description="장소 명칭")


class BasePreference(BaseModel):
    """
    산책 경로 추천을 위해 필요한 공통 의도 정보입니다.
    """
    origin: Optional[Location] = Field(None, description="출발지 정보")
    purpose: Optional[str] = Field(None, description="산책 목적")

    # 챗봇 자연어 의도를 route/profile 계층에 연결하기 위한 보존 필드입니다.
    profile_name: str = Field(
        "default",
        description="route_engine profile 후보명(default, quiet, flat, safe, scenic, child, running)",
    )
    child_friendly: bool = Field(False, description="어린이 동반, 유모차 등 안전 우선 여부")
    unsupported_preferences: list[str] = Field(
        default_factory=list,
        description="현재 route_engine이 직접 지원하지 않는 요구사항 보존",
    )


class CircularPreference(BasePreference):
    """
    순환 경로일 때 채워야 할 필수 정보입니다.
    """
    mode: CircularMode
    target_km: Optional[float] = None


class OnewayPreference(BasePreference):
    """
    편도 경로일 때 채워야 할 필수 정보입니다.
    """
    mode: OnewayMode
    destination: Optional[Location] = None
    target_km: Optional[float] = None


class OnewayShortestPreference(BasePreference):
    """
    다익스트라 기반 최단 경로일 때 채워야 할 필수 정보입니다.
    """
    mode: OnewayMode = OnewayMode.SHORTEST
    destination: Optional[Location] = None


class State(BaseModel):
    """
    대화 상태 관련 정보입니다.
    """
    user_uuid: str
    current_location: Location

    mode: Optional[Union[CircularMode, OnewayMode]] = None
    user_context: Optional[
        Union[CircularPreference, OnewayPreference, OnewayShortestPreference]
    ] = None

    origin_candidate: Optional[List[Location]] = None
    destination_candidate: Optional[List[Location]] = None

    weather_data: Optional[EnvironmentInfo] = None
    route_result: Optional[WalkRouteResponse] = None
    is_complete: bool = False
    user_prompt: str = ""
    response: str = ""
