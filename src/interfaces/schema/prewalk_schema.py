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
    user_prompt: str = Field(
        default="",
        description="사용자 산책 요청 문장, 또는 확인 응답에 곁들인 교정 내용. confirmation을 안 보내면(일반 대화 턴) 공백일 수 없음",
    )
    confirmation: Optional[bool] = Field(
        default=None,
        description="확인 질문(예: '이 코스로 진행할까요?')에 대한 FE 버튼 응답. 확인 대기 중이 아니면 생략",
    )
    lat: float = Field(description="현재 위도. 서울 영역의 유한한 좌표")
    lon: float = Field(description="현재 경도. 서울 영역의 유한한 좌표")

    @model_validator(mode="after")
    def check_user_prompt_required_without_confirmation(self) -> "ChatRequest":
        # confirmation이 없으면(일반 대화 턴) 빈 user_prompt를 막는다. confirmation이 있으면
        # (확인 응답 턴) "yes"는 교정할 내용이 없어 user_prompt가 비어 있을 수 있고, "no"는
        # 있으면 그대로 Extractor가 교정 내용으로 파싱한다 — 둘 다 필수로 강제하지 않는다.
        if self.confirmation is None and not self.user_prompt.strip():
            raise ValueError("user_prompt는 공백일 수 없습니다.")
        return self

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
