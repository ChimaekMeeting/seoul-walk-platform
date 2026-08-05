from pydantic import BaseModel, Field, model_validator
from typing import Optional, Union, List
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
        Union[CircularPreference, OnewayPreference, OnewayShortestPreference]
    ] = None

    origin_candidate: Optional[List[Location]] = None
    destination_candidate: Optional[List[Location]] = None

    route_result: Optional[List[WalkRouteResponse]] = None
    is_complete: bool = False
    awaiting_confirmation: bool = False
    user_prompt: str  = ""
    response:    str  = ""
    themes: List[str] = Field(default_factory=list)
    profile: Optional[ScoringProfile] = None
