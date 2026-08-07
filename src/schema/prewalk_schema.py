from pydantic import BaseModel, Field, model_validator
from typing import Literal, Optional, Union, List
from src.interfaces.schema.walk_schema import WalkMode, WalkRouteResponse
from src.route_engine.profiles import ScoringProfile


class Location(BaseModel):
    """
    위치(출발지, 목적지) 관련 정보입니다.
    """
    lat: Optional[float] = Field(None, description="위도(Latitude)")
    lon: Optional[float] = Field(None, description="경도(Longitude)")
    address: Optional[str] = Field(None, description="지번 주소 또는 도로명 주소")
    place_name: Optional[str] = Field(None, description="장소 명칭")

    @model_validator(mode="before")
    @classmethod
    def _coerce_bare_string(cls, value):
        """
        LLM이 Location 대신 장소명 문자열만 넘기는 경우, place_name으로 감싸 받아들인다.
        (예: origin="홍대" -> Location(place_name="홍대"))
        """
        if isinstance(value, str):
            return {"place_name": value}
        return value


class BasePreference(BaseModel):
    origin: Optional[Location] = None


class CircularPreference(BasePreference):
    """
    순환 경로(circular_random)일 때 채워야 할 필수 정보입니다.
    """
    mode:      WalkMode = WalkMode.CIRCULAR_RANDOM
    target_km: Optional[float] = None


class OnewayPreference(BasePreference):
    """
    편도 우회 경로(oneway_random)일 때 채워야 할 필수 정보입니다.
    """
    mode:        WalkMode = WalkMode.ONEWAY_RANDOM
    destination: Optional[Location] = None
    target_km:   Optional[float]    = None


class OnewayShortestPreference(BasePreference):
    """
    다익스트라 기반 최단 편도 경로(oneway_shortest)일 때 채워야 할 필수 정보입니다.
    """
    mode:        WalkMode = WalkMode.ONEWAY_SHORTEST
    destination: Optional[Location] = None


class GPSArtPreference(BasePreference):
    """
    GPS Art 기반 경로일 때 채워야 할 필수 정보입니다.
    """
    mode:      WalkMode = WalkMode.GPS_ART
    shape:     Optional[str] = None
    target_km: Optional[float] = None


# route_schema.WaypointLegMode와 동일한 값이지만, route_schema -> walk_schema -> route_engine.profiles
# -> route_schema로 이어지는 기존 순환 임포트를 피하기 위해 여기서도 로컬로 재정의한다.
WaypointLegMode = Literal["oneway_shortest", "oneway_random"]


class WaypointLegPreference(BaseModel):
    """
    경유지 구간(leg) 하나의 이동 방식입니다. 언급이 없으면 최단 경로로 간주합니다.
    """
    mode:      WaypointLegMode = "oneway_shortest"
    target_km: Optional[float] = None  # mode가 oneway_random일 때만 사용


class WayPointPreference(BasePreference):
    """
    경유지를 거쳐가는 경로일 때 채워야 할 필수 정보입니다.
    origin -> waypoints[0] -> ... -> waypoints[-1] -> destination 순으로 이동하며,
    legs[i]가 그 순서상 i번째 구간의 이동 방식입니다(길이는 waypoints 길이 + 1).
    순환 코스를 원하면 destination을 origin과 동일한 위치로 설정합니다.
    """
    mode:        WalkMode = WalkMode.WAYPOINT
    waypoints:   List[Location] = Field(default_factory=list)
    destination: Optional[Location] = None
    legs:        List[WaypointLegPreference] = Field(default_factory=list)


class ConfirmationResult(BaseModel):
    """
    확인 질문에 대한 사용자 응답의 긍정/부정 분류 결과입니다.
    """
    is_positive: bool = Field(description="사용자 응답이 확인 질문에 긍정(진행)인지 여부")


class State(BaseModel):
    """
    대화 상태 관련 정보입니다.
    """
    user_id: int
    current_location: Location
    access_token: Optional[str] = None

    mode: Optional[WalkMode] = None
    user_context: Optional[
        Union[
            CircularPreference,
            OnewayPreference,
            OnewayShortestPreference,
            GPSArtPreference,
            WayPointPreference,
        ]
    ] = None

    origin_candidate: Optional[List[Location]] = None
    destination_candidate: Optional[List[Location]] = None
    waypoint_candidates: Optional[List[Optional[List[Location]]]] = None

    route_result: Optional[List[WalkRouteResponse]] = None
    is_complete: bool = False
    awaiting_confirmation: bool = False
    user_prompt: str  = ""
    response:    str  = ""
    themes: List[str] = Field(default_factory=list)
    profile: Optional[ScoringProfile] = None
