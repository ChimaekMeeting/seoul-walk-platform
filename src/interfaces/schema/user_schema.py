from datetime import datetime
from pydantic import BaseModel, field_validator
from typing import Optional, List

from src.interfaces.schema.auth_schema import Status


class UserResponse(BaseModel):
    status: Status
    nickname: Optional[str] = None


class RouteHistoryItem(BaseModel):
    id: int
    mode: str
    origin_lat: float
    origin_lon: float
    destination_lat: Optional[float] = None
    destination_lon: Optional[float] = None
    coordinates: list
    total_km: float
    is_favorite: bool = False
    created_at: datetime

    @field_validator("is_favorite", mode="before")
    @classmethod
    def none_to_false(cls, v):
        return v if v is not None else False

    class Config:
        from_attributes = True


class RouteHistoryResponse(BaseModel):
    histories: List[RouteHistoryItem]
    total: int