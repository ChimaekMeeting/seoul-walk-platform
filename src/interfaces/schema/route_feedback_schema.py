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
    # 더 이상 반환하지 않는다(#516). 후보 경로가 없어도 별점만으로 갱신하고, 별점이 모두 비어 있어도
    # 정상 요청으로 보고 SUCCESS(현재 가중치 그대로)를 돌려준다. 기존 응답을 파싱하는 클라이언트
    # 호환을 위해 값만 남긴다.
    INSUFFICIENT_CANDIDATES = "insufficient_candidates"


class RouteFeedbackRequest(BaseModel):
    """
    산책 후 피드백 제출 요청 스키마입니다. 세 별점은 선택 입력이며 값이 있으면 1~5점이어야 합니다(#516).
    비어 있는(생략 또는 null) 별점은 서비스가 3점(중립)으로 간주합니다. 세 별점이 모두 비어 있으면
    피드백으로 저장하거나 학습하지 않고 현재 장기 가중치를 그대로 돌려줍니다.
    """
    rating_safety:  Optional[int] = Field(default=None, ge=1, le=5, description="안전 만족도 별점(1~5, 생략 시 3점 간주)")
    rating_comfort: Optional[int] = Field(default=None, ge=1, le=5, description="편안 만족도 별점(1~5, 생략 시 3점 간주)")
    rating_overall: Optional[int] = Field(default=None, ge=1, le=5, description="전체 경로 만족도 별점(1~5, 생략 시 3점 간주)")


class RouteFeedbackResponse(BaseModel):
    """
    피드백 제출 응답 스키마입니다. 장기 프로필이 갱신됐다면 갱신 후 값을 반환합니다.
    """
    status: RouteFeedbackStatus
    weights_safety:  Optional[float] = None
    weights_comfort: Optional[float] = None
