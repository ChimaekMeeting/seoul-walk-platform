from enum import Enum
from typing import Optional

from pydantic import BaseModel, field_validator, model_validator

from src.schema.prewalk_schema import State
from src.interfaces.validators.coord_validator import (
    validate_coordinate_not_empty,
    validate_coordinate_parseable,
    validate_coordinates,
    validate_seoul_bounding_box,
)


class InitRequest(BaseModel):
    """
    챗봇 세션 생성을 위한 입력 스키마
    """
    user_uuid: str
    lat: float
    lon: float

    @field_validator("lat", "lon", mode="before")
    @classmethod
    def check_coordinate_not_empty(cls, value: object) -> object:
        return validate_coordinate_not_empty(value)

    @field_validator("lat", "lon", mode="before")
    @classmethod
    def check_coordinate_parseable(cls, value: object) -> object:
        return validate_coordinate_parseable(value)

    @model_validator(mode="after")
    def check_coordinates(self) -> "InitRequest":
        validate_coordinates(self.lat, self.lon)
        validate_seoul_bounding_box(self.lat, self.lon)
        return self


class ChatRequest(BaseModel):
    """
    챗봇과 상호작용을 위한 입력 스키마
    """
    thread_id: str
    user_prompt: str


class ChatStatus(str, Enum):
    SUCCESS = "success"
    ACCESS_EXPIRED_TOKEN = "access_expired_token"
    INVALID_TOKEN = "invalid_token"
    SESSION_NOT_FOUND = "session_not_found"
    UNACCESSIBLE = "unaccessible"


class ChatResponse(BaseModel):
    """
    챗봇과 상호작용을 통해 제공되는 출력 스키마
    """
    status: ChatStatus
    thread_id: Optional[str] = None
    state: Optional[State] = None
