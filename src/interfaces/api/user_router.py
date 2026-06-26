"""
src/interfaces/api/user_router.py

/api/user 하위 엔드포인트 정의.
현재 온보딩 설문 제출(POST /api/user/survey)을 제공합니다.
"""

from fastapi import APIRouter, Cookie, Depends, HTTPException
import logging

from src.interfaces.dependencies import get_survey_service, get_auth_service, get_user_service
from src.interfaces.schema.survey_schema import SurveyRequest, SurveyResponse, SurveyStatusResponse
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

logger = logging.getLogger(__name__)

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
            logger.warning("경로 기록 조회 인증 실패: status=%s", status.value)
            raise HTTPException(status_code=401, detail=status.value)

        user = UserRepository.find_by_provider_and_provider_id(provider, provider_id)
        if user is None:
            logger.warning("경로 기록 조회 - 사용자를 찾을 수 없습니다: provider=%s", provider)
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
        logger.exception("경로 기록 조회 중 오류가 발생했습니다.")
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
            logger.warning("즐겨찾기 토글 인증 실패: status=%s, history_id=%s", status.value, history_id)
            raise HTTPException(status_code=401, detail=status.value)

        user = UserRepository.find_by_provider_and_provider_id(provider, provider_id)
        if user is None:
            logger.warning("즐겨찾기 토글 - 사용자를 찾을 수 없습니다: provider=%s", provider)
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

        history = RouteHistoryRepository.toggle_favorite(history_id, user.id)
        if history is None:
            logger.warning("즐겨찾기 토글 - 경로 기록을 찾을 수 없습니다: history_id=%s, user_id=%s", history_id, user.id)
            raise HTTPException(status_code=404, detail="경로 기록을 찾을 수 없습니다.")

        return RouteHistoryItem.model_validate(history)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("즐겨찾기 토글 중 오류가 발생했습니다: history_id=%s", history_id)
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
            logger.warning("경로 기록 상세 조회 인증 실패: status=%s, history_id=%s", status.value, history_id)
            raise HTTPException(status_code=401, detail=status.value)

        user = UserRepository.find_by_provider_and_provider_id(provider, provider_id)
        if user is None:
            logger.warning("경로 기록 상세 조회 - 사용자를 찾을 수 없습니다: provider=%s", provider)
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

        history = RouteHistoryRepository.find_by_id(history_id, user.id)
        if history is None:
            logger.warning("경로 기록 상세 조회 - 경로 기록을 찾을 수 없습니다: history_id=%s, user_id=%s", history_id, user.id)
            raise HTTPException(status_code=404, detail="경로 기록을 찾을 수 없습니다.")

        return RouteHistoryItem.model_validate(history)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("경로 기록 상세 조회 중 오류가 발생했습니다: history_id=%s", history_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/survey", response_model=SurveyStatusResponse)
def get_survey_status(
    access_token: str = Cookie(None),
    service: SurveyService = Depends(get_survey_service),
):
    """설문 완료 여부를 반환합니다."""
    return service.get_status(access_token)
