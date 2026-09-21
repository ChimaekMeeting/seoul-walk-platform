from datetime import date, datetime
from enum import Enum
from typing import Optional, List

from pydantic import BaseModel, field_validator

from src.interfaces.schema.auth_schema import Status
from src.interfaces.schema.walk_schema import WalkProgressStatus


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
    # 출발지/도착지 표시용 이름(#520). 챗봇을 거치지 않은 경로와 이전 기록은 None.
    origin_address: Optional[str] = None
    origin_place_name: Optional[str] = None
    destination_address: Optional[str] = None
    destination_place_name: Optional[str] = None
    # 산책 진행 상태: recommended(추천만 받음) / in_progress(산책 시작) / completed(완주). 이전 기록은 recommended.
    walk_status: str = "recommended"
    # 완주한 날짜(한국 시간 기준). 완주하지 않은 경로는 None.
    walked_on: Optional[date] = None

    @field_validator("is_favorite", mode="before")
    @classmethod
    def none_to_false(cls, v):
        return v if v is not None else False

    @field_validator("walk_status", mode="before")
    @classmethod
    def none_to_recommended(cls, v):
        return v if v is not None else "recommended"

    class Config:
        from_attributes = True


class RouteWalkProgressResponse(BaseModel):
    """POST /api/user/routes/{id}/start, /complete 응답(#520).

    walk_status는 요청 성공 여부가 아니라 처리 후 산책 진행 상태다(recommended / in_progress / completed).
    /favorite, /feedback의 status(성공 여부)와 헷갈리지 않도록 필드명을 walk_status로 둔다.
    요청 실패(인증 오류, 없는 경로)는 다른 /routes 엔드포인트처럼 HTTP 401/404로 돌려준다.
    walked_on은 완주한 날짜(한국 시간 기준)이며 완주하지 않았으면 null이다.
    """
    walk_status: WalkProgressStatus
    walked_on: Optional[date] = None


class RouteHistoryResponse(BaseModel):
    histories: List[RouteHistoryItem]
    total: int
