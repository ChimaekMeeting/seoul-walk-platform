"""
src/interfaces/schema/survey_schema.py

온보딩 설문 API의 요청/응답 스키마 정의.
"""
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


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

    tags: 프론트가 보내는 온보딩 선택 태그 목록. 지금 프론트에서 넘어오는 값은
        "안전"/"편안" 두 가지뿐이며(선택 안 한 축은 목록에서 빠짐), survey_service.
        submit()이 이 목록에서 "안전"/"편안" 포함 여부를 뽑아 _safety_comfort_deltas의
        k=0.3 배분 공식 입력으로 쓴다 — 장기 프로필의 weights_safety/weights_comfort
        초기값을 함께 결정한다(장기 프로필이 실제로 추적하는 축이 이 둘뿐이라 온보딩
        초기값도 이 공식 하나로 통일했다). selected_tags에 참고용으로 그대로 저장도 됨.
    distance: 선호 산책 거리 선택지 (선택 안 하면 null)
    """
    tags: List[str] = Field(default_factory=list)
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
    weights_comfort: Optional[float] = None

class SurveyStatusResponse(BaseModel):
    """설문 완료 여부 및 저장된(=영속) 장기 프로필 가중치 조회 응답 스키마입니다."""
    status: SurveyStatus
    survey_completed: bool
    default_target_km: Optional[float] = None
    weights_safety: Optional[float] = None
    weights_comfort: Optional[float] = None
    selected_tags: Optional[List[str]] = None
