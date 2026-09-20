from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    model_config = ConfigDict(json_schema_extra={"example": {"lat": 37.5665, "lon": 126.9780}})

    lat: float = Field(description="현재 위도. 서울 영역의 유한한 좌표")
    lon: float = Field(description="현재 경도. 서울 영역의 유한한 좌표")

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
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "thread_id": "8b3018da-5a11-4f24-9c42-39fd630888c5",
                "user_prompt": "광화문에서 3km 순환 산책을 추천해줘",
                "lat": 37.5665,
                "lon": 126.9780,
            }
        }
    )

    thread_id: str = Field(min_length=1, description="/api/prewalk/init이 발급한 세션 ID")
    user_prompt: str = Field(min_length=1, description="사용자 산책 요청 문장. 공백만 입력할 수 없음")
    lat: float = Field(description="현재 위도. 서울 영역의 유한한 좌표")
    lon: float = Field(description="현재 경도. 서울 영역의 유한한 좌표")

    @field_validator("user_prompt")
    @classmethod
    def check_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("user_prompt는 공백일 수 없습니다.")
        return v

    @field_validator("lat", "lon", mode="before")
    @classmethod
    def check_coordinate_not_empty(cls, value: object) -> object:
        return validate_coordinate_not_empty(value)

    @field_validator("lat", "lon", mode="before")
    @classmethod
    def check_coordinate_parseable(cls, value: object) -> object:
        return validate_coordinate_parseable(value)

    @model_validator(mode="after")
    def check_coordinates(self) -> "ChatRequest":
        validate_coordinates(self.lat, self.lon)
        validate_seoul_bounding_box(self.lat, self.lon)
        return self


class ChatStatus(str, Enum):
    SUCCESS = "success"
    ACCESS_EXPIRED_TOKEN = "access_expired_token"
    INVALID_TOKEN = "invalid_token"
    SESSION_NOT_FOUND = "session_not_found"
    UNACCESSIBLE = "unaccessible"
    INTERNAL_ERROR = "internal_error"


class ChatResponse(BaseModel):
    """
    챗봇과 상호작용을 통해 제공되는 출력 스키마
    """
    status: ChatStatus
    thread_id: Optional[str] = None
    state: Optional[State] = None
