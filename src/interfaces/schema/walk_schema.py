from typing import Optional, List
from pydantic import BaseModel, Field


class Coordinate(BaseModel):
    lat: float
    lon: float


class LocationInfo(BaseModel):
    place_name: str = ""
    address: str = ""
    coordinate: Coordinate


class WalkRouteRequest(BaseModel):
    mode: str = Field(..., description="circular | oneway_shortest | oneway_random")
    distance_km: float = Field(3.0, ge=1.0, le=20.0)
    child_friendly: bool = Field(False)
    origin: LocationInfo
    destination: Optional[LocationInfo] = None
    purpose: str = Field("산책")

    # 챗봇/프론트에서 추출한 사용자 선호를 route_engine profile로 전달하기 위한 값
    # (참고: 그늘/시원함 등 전용 프로필이 없는 항목은 프롬프트 단에서 'quiet'으로 임시 매핑됨)
    profile_name: str = Field("default", description="지원 프로필: default, quiet, flat, safe, scenic, child, running")


class WalkRouteResponse(BaseModel):
    mode: str
    coordinates: List[List[float]]
    total_distance_km: float
    error: Optional[str] = None
