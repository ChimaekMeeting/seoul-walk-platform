"""
src/interfaces/api/user_router.py

/api/user 하위 엔드포인트 정의.
현재 온보딩 설문 제출(POST /api/user/survey)을 제공합니다.
"""
from fastapi import APIRouter, Cookie, Depends

from src.interfaces.dependencies import get_survey_service, get_user_service
from src.interfaces.schema.survey_schema import SurveyRequest, SurveyResponse
from src.interfaces.schema.user_schema import UserMeResponse, UserUpdateRequest, UserUpdateResponse
from src.service.user.survey_service import SurveyService
from src.service.user.user_service import UserService

router = APIRouter(
    prefix="/api/user",
    tags=["user"]
)


@router.get("/me", response_model=UserMeResponse)
def get_me(
    access_token: str = Cookie(None),
    service: UserService = Depends(get_user_service),
):
    """
    온보딩 설문 결과를 제출합니다.

    input : 키워드 태그 목록, 선호 거리 선택지
    output: 저장된 사용자 가중치 프로필
    """
    return service.get_me(access_token)


@router.patch("/me", response_model=UserUpdateResponse)
def update_me(
    request: UserUpdateRequest,
    access_token: str = Cookie(None),
    service: UserService = Depends(get_user_service),
):
    return service.update_me(access_token, request.nickname)


@router.post("/survey", response_model=SurveyResponse)
def submit_survey(
    request: SurveyRequest,
    access_token: str = Cookie(None),
    service: SurveyService = Depends(get_survey_service),
):
    return service.submit(access_token, request)
