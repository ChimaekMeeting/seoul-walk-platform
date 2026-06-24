"""
src/interfaces/schema/survey_schema.py

온보딩 설문 API의 요청/응답 스키마 정의.
"""
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel


class DistanceOption(str, Enum):
    """
    선호 산책 거리 선택지입니다.
    """
    SLOW   = "slow"    # ~2km
    NORMAL = "normal"  # 2–4km
    FAST   = "fast"    # 4km+


class SurveyStatus(str, Enum):
    SUCCESS              = "success"
    ACCESS_EXPIRED_TOKEN = "access_expired_token"
    INVALID_TOKEN        = "invalid_token"
    USER_NOT_FOUND       = "user_not_found"


class SurveyRequest(BaseModel):
    """
    온보딩 설문 제출 요청 스키마입니다.

    tags: 사용자가 선택한 키워드 태그 목록
    distance: 선호 산책 거리 선택지 (선택 안 하면 null)
    """
    tags: List[str] = []
    distance: Optional[DistanceOption] = None


class SurveyResponse(BaseModel):
    """
    온보딩 설문 제출 응답 스키마입니다.

    저장된 가중치 값을 그대로 반환합니다.
    인증 실패 또는 오류 시 status만 반환되고 나머지 필드는 null입니다.
    """
    status: SurveyStatus
    default_target_km: Optional[float] = None
    weights_safety: Optional[float] = None
    weights_nature: Optional[float] = None
    weights_slope: Optional[float] = None
    weights_running: Optional[float] = None
    weights_landmark: Optional[float] = None
    weights_child: Optional[float] = None
    
class SurveyStatusResponse(BaseModel):
    """설문 완료 여부 및 저장된 가중치 조회 응답 스키마입니다."""
    survey_completed: bool
    default_target_km: Optional[float] = None
    weights_safety: Optional[float] = None
    weights_nature: Optional[float] = None
    weights_slope: Optional[float] = None
    weights_running: Optional[float] = None
    weights_landmark: Optional[float] = None
    weights_child: Optional[float] = None
