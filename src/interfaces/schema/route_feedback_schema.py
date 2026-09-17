"""
src/interfaces/schema/route_feedback_schema.py

산책 후 피드백(별점) API의 요청/응답 스키마 정의.
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RouteFeedbackStatus(str, Enum):
    SUCCESS                = "success"
    ACCESS_EXPIRED_TOKEN   = "access_expired_token"
    REFRESH_EXPIRED_TOKEN  = "refresh_expired_token"
    INVALID_TOKEN          = "invalid_token"
    USER_NOT_FOUND        = "user_not_found"
    ROUTE_NOT_FOUND       = "route_not_found"
    # 대표 후보뿐이었던 경로(경쟁 후보가 없어 대조값을 계산할 수 없음) — 별점은
    # 저장하되 장기 프로필 가중치는 갱신하지 않는다.
    INSUFFICIENT_CANDIDATES = "insufficient_candidates"


class RouteFeedbackRequest(BaseModel):
    """
    산책 후 피드백 제출 요청 스키마입니다. 세 별점 모두 1~5점 필수입니다.
    """
    rating_safety:  int = Field(ge=1, le=5, description="안전 만족도 별점(1~5)")
    rating_comfort: int = Field(ge=1, le=5, description="편안 만족도 별점(1~5)")
    rating_overall: int = Field(ge=1, le=5, description="전체 경로 만족도 별점(1~5)")


class RouteFeedbackResponse(BaseModel):
    """
    피드백 제출 응답 스키마입니다. 장기 프로필이 갱신됐다면 갱신 후 값을 반환합니다.
    """
    status: RouteFeedbackStatus
    weights_safety:  Optional[float] = None
    weights_comfort: Optional[float] = None
