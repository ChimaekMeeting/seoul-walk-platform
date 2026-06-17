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


class WalkRouteResponse(BaseModel):
    mode: str
    coordinates: List[List[float]]
    total_distance_km: float
    error: Optional[str] = None
