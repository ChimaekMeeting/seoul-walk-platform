from datetime import datetime
from enum import Enum
from typing import Optional, List

from pydantic import BaseModel, field_validator

from src.interfaces.schema.auth_schema import Status


class UserResponse(BaseModel):
    status: Status
    nickname: Optional[str] = None


class UserStatus(str, Enum):
    SUCCESS              = "success"
    ACCESS_EXPIRED_TOKEN = "access_expired_token"
    INVALID_TOKEN        = "invalid_token"
    USER_NOT_FOUND       = "user_not_found"
    INVALID_NICKNAME     = "invalid_nickname"


class UserMeResponse(BaseModel):
    status: UserStatus
    nickname: Optional[str] = None
    survey_completed: Optional[bool] = None


class UserUpdateRequest(BaseModel):
    nickname: str

    @field_validator("nickname")
    @classmethod
    def validate_nickname(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("닉네임을 입력해 주세요.")
        if len(v) > 50:
            raise ValueError("닉네임은 50자 이내로 입력해 주세요.")
        return v


class UserUpdateResponse(BaseModel):
    status: UserStatus
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
