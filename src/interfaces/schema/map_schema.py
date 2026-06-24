from pydantic import BaseModel


class FacilityResponse(BaseModel):
    name: str
    lon: float
    lat: float
    address: str


class PointResponse(BaseModel):
    lat: float
    lon: float
    category: str


class LandmarkResponse(BaseModel):
    lat: float
    lon: float


class EdgeResponse(BaseModel):
    path: list[list[float]]
    link_id: str
