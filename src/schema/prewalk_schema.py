




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
    origin: Optional[Location] = None
    purpose: Optional[str]     = None


class CircularPreference(BasePreference):
    """
    순환 경로일 때 채워야 할 필수 정보입니다.
    """
    mode:      CircularMode
    target_km: Optional[float] = None


class OnewayPreference(BasePreference):
    """
    편도 경로일 때 채워야 할 필수 정보입니다.
    """
    mode:        OnewayMode
    destination: Optional[Location] = None
    target_km:   Optional[float]    = None


class OnewayShortestPreference(BasePreference):
    """
    다익스트라 기반 최단 경로일 때 채워야 할 필수 정보입니다.
    """
    mode:        OnewayMode     = OnewayMode.SHORTEST
    destination: Optional[Location] = None


class State(BaseModel):
    """
    대화 상태 관련 정보입니다.
    """
    user_id: int
    current_location: Location
    access_token: Optional[str] = None

    mode: Optional[Union[CircularMode, OnewayMode]] = None
    user_context: Optional[
        Union[CircularPreference, OnewayPreference, OnewayShortestPreference]
    ] = None

    origin_candidate: Optional[List[Location]] = None
    destination_candidate: Optional[List[Location]] = None

    weather_data: Optional[EnvironmentInfo] = None
    route_result: Optional[WalkRouteResponse] = None
    is_complete: bool = False
    user_prompt: str  = ""
    response:    str  = ""
    themes: List[str] = []
