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


class EdgeResponse(BaseModel):
    path: list[list[float]]
    link_id: str
