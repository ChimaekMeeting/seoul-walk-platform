"""
src/interfaces/api/user_router.py

/api/user 하위 엔드포인트 정의.
현재 온보딩 설문 제출(POST /api/user/survey)을 제공합니다.
"""

from fastapi import APIRouter, Cookie, Depends, HTTPException

from src.interfaces.dependencies import get_survey_service, get_auth_service, get_user_service
from src.interfaces.schema.survey_schema import SurveyRequest, SurveyResponse
from src.interfaces.schema.user_schema import (
    UserMeResponse, UserUpdateRequest, UserUpdateResponse,
    RouteHistoryResponse, RouteHistoryItem,
)
from src.service.user.survey_service import SurveyService
from src.service.user.user_service import UserService
from src.repository.user.user_repository import UserRepository
from src.repository.user.route_history_repository import RouteHistoryRepository
from src.service.user.auth_service import AuthService
from src.interfaces.schema.auth_schema import Status
import traceback

router = APIRouter(prefix="/api/user", tags=["user"])


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


@router.get("/routes", response_model=RouteHistoryResponse)
def get_route_histories(
    limit: int = 20,
    offset: int = 0,
    access_token: str = Cookie(None),
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    로그인한 사용자의 추천 경로 기록을 조회합니다.
    """
    try:
        status, provider, provider_id = auth_service.check_access_token(access_token)
        if status != Status.SUCCESS:
            raise HTTPException(status_code=401, detail=status.value)

        user = UserRepository.find_by_provider_and_provider_id(provider, provider_id)
        if user is None:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

        histories = RouteHistoryRepository.find_by_user_id(
            user.id, limit=limit, offset=offset
        )
        return RouteHistoryResponse(
            histories=[RouteHistoryItem.model_validate(h) for h in histories],
            total=len(histories),
        )
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/routes/{history_id}/favorite", response_model=RouteHistoryItem)
def toggle_favorite(
    history_id: int,
    access_token: str = Cookie(None),
    auth_service: AuthService = Depends(get_auth_service),
):
    """경로 기록의 즐겨찾기를 토글합니다."""
    try:
        status, provider, provider_id = auth_service.check_access_token(access_token)
        if status != Status.SUCCESS:
            raise HTTPException(status_code=401, detail=status.value)

        user = UserRepository.find_by_provider_and_provider_id(provider, provider_id)
        if user is None:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

        history = RouteHistoryRepository.toggle_favorite(history_id, user.id)
        if history is None:
            raise HTTPException(status_code=404, detail="경로 기록을 찾을 수 없습니다.")

        return RouteHistoryItem.model_validate(history)
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/routes/{history_id}", response_model=RouteHistoryItem)
def get_route_history(
    history_id: int,
    access_token: str = Cookie(None),
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    특정 추천 경로 기록 상세를 조회합니다.
    """
    try:
        status, provider, provider_id = auth_service.check_access_token(access_token)
        if status != Status.SUCCESS:
            raise HTTPException(status_code=401, detail=status.value)

        user = UserRepository.find_by_provider_and_provider_id(provider, provider_id)
        if user is None:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

        history = RouteHistoryRepository.find_by_id(history_id, user.id)
        if history is None:
            raise HTTPException(status_code=404, detail="경로 기록을 찾을 수 없습니다.")

        return RouteHistoryItem.model_validate(history)
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
