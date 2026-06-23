"""
src/interfaces/api/user_router.py

/api/user 하위 엔드포인트 정의.
현재 온보딩 설문 제출(POST /api/user/survey)을 제공합니다.
"""
from fastapi import APIRouter, Cookie, Depends

from src.interfaces.dependencies import get_survey_service
from src.interfaces.schema.survey_schema import SurveyRequest, SurveyResponse
from src.service.user.survey_service import SurveyService

router = APIRouter(
    prefix="/api/user",
    tags=["user"]
)


@router.post("/survey", response_model=SurveyResponse)
def submit_survey(
    request: SurveyRequest,
    access_token: str = Cookie(None),
    service: SurveyService = Depends(get_survey_service),
):
    """
    온보딩 설문 결과를 제출합니다.

    input : 키워드 태그 목록, 선호 거리 선택지
    output: 저장된 사용자 가중치 프로필
    """
    return service.submit(access_token, request)
