"""
src/interfaces/api/user_router.py

/api/user 하위 엔드포인트 정의.
현재 온보딩 설문 제출(POST /api/user/survey)을 제공합니다.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
import logging

from src.interfaces.dependencies import (
    get_survey_service,
    get_auth_service,
    get_user_service,
    get_longterm_profile_service,
)
from src.interfaces.schema.survey_schema import SurveyRequest, SurveyResponse, SurveyStatusResponse
from src.interfaces.schema.route_feedback_schema import RouteFeedbackRequest, RouteFeedbackResponse
from src.interfaces.schema.user_schema import (
    UserMeResponse, UserUpdateRequest, UserUpdateResponse,
    RouteHistoryResponse, RouteHistoryItem,
    RouteWalkProgressResponse,
)
from src.interfaces.schema.walk_schema import WalkProgressStatus
from src.service.user.survey_service import SurveyService
from src.service.user.user_service import UserService
from src.service.user.longterm_profile_service import LongTermProfileService
from src.repository.user.user_repository import UserRepository
from src.repository.user.route_history_repository import RouteHistoryRepository
from src.service.user.auth_service import AuthService
from src.interfaces.schema.auth_schema import Status
from src.interfaces.errors import SAFE_INTERNAL_ERROR_DETAIL, log_unexpected_error
from src.interfaces.security import resolve_access_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/user", tags=["user"])


@router.get("/me", response_model=UserMeResponse)
def get_me(
    access_token: str | None = Depends(resolve_access_token),
    service: UserService = Depends(get_user_service),
):
    return service.get_me(access_token)


@router.patch("/me", response_model=UserUpdateResponse)
def update_me(
    request: UserUpdateRequest,
    access_token: str | None = Depends(resolve_access_token),
    service: UserService = Depends(get_user_service),
):
    return service.update_me(access_token, request.nickname)


@router.post("/survey", response_model=SurveyResponse)
def submit_survey(
    request: SurveyRequest,
    access_token: str | None = Depends(resolve_access_token),
    service: SurveyService = Depends(get_survey_service),
):
    return service.submit(access_token, request)


@router.get("/routes", response_model=RouteHistoryResponse)
def get_route_histories(
    limit: int = 20,
    offset: int = 0,
    is_favorite: Optional[bool] = None,
    access_token: str | None = Depends(resolve_access_token),
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    로그인한 사용자의 추천 경로 기록을 조회합니다.
    is_favorite을 지정하면 즐겨찾기 여부로 필터링합니다(예: true → 즐겨찾기만).
    """
    try:
        status, provider, provider_id = auth_service.check_access_token(
            access_token
        )
        if status != Status.SUCCESS:
            logger.warning("경로 기록 조회 인증 실패: status=%s", status.value)
            raise HTTPException(status_code=401, detail=status.value)

        user = UserRepository.find_by_provider_and_provider_id(provider, provider_id)
        if user is None:
            logger.warning("route_history_list_user_not_found")
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

        histories = RouteHistoryRepository.find_by_user_id(
            user.id, limit=limit, offset=offset, is_favorite=is_favorite
        )
        return RouteHistoryResponse(
            histories=[RouteHistoryItem.model_validate(h) for h in histories],
            total=len(histories),
        )
    except HTTPException:
        raise
    except Exception as e:
        log_unexpected_error(logger, "route_history_list_unexpected_error", e)
        raise HTTPException(status_code=500, detail=SAFE_INTERNAL_ERROR_DETAIL) from e


@router.patch("/routes/{history_id}/favorite", response_model=RouteHistoryItem)
def toggle_favorite(
    history_id: int,
    access_token: str | None = Depends(resolve_access_token),
    auth_service: AuthService = Depends(get_auth_service),
):
    """경로 기록의 즐겨찾기를 토글합니다."""
    try:
        status, provider, provider_id = auth_service.check_access_token(
            access_token
        )
        if status != Status.SUCCESS:
            logger.warning("route_favorite_auth_failed | status=%s", status.value)
            raise HTTPException(status_code=401, detail=status.value)

        user = UserRepository.find_by_provider_and_provider_id(provider, provider_id)
        if user is None:
            logger.warning("route_favorite_user_not_found")
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

        history = RouteHistoryRepository.toggle_favorite(history_id, user.id)
        if history is None:
            logger.warning("route_favorite_not_found")
            raise HTTPException(status_code=404, detail="경로 기록을 찾을 수 없습니다.")

        return RouteHistoryItem.model_validate(history)
    except HTTPException:
        raise
    except Exception as e:
        log_unexpected_error(logger, "route_favorite_unexpected_error", e)
        raise HTTPException(status_code=500, detail=SAFE_INTERNAL_ERROR_DETAIL) from e


def _walk_progress_response(history) -> RouteWalkProgressResponse:
    """경로 기록의 현재 산책 진행 상태를 응답으로 만든다(walk_status가 없던 이전 기록은 recommended)."""
    return RouteWalkProgressResponse(
        walk_status=WalkProgressStatus(history.walk_status or WalkProgressStatus.RECOMMENDED.value),
        walked_on=history.walked_on,
    )


def _update_walk_progress(history_id: int, access_token: str | None, auth_service: AuthService, update, log_name: str):
    """산책 시작/완주 기록 엔드포인트의 공통 처리(인증 -> 소유 확인 -> 상태 기록 -> 진행 상태 응답)."""
    try:
        status, provider, provider_id = auth_service.check_access_token(access_token)
        if status != Status.SUCCESS:
            logger.warning("%s_auth_failed | status=%s", log_name, status.value)
            raise HTTPException(status_code=401, detail=status.value)

        user = UserRepository.find_by_provider_and_provider_id(provider, provider_id)
        if user is None:
            logger.warning("%s_user_not_found", log_name)
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

        history = update(history_id, user.id)
        if history is None:
            logger.warning("%s_not_found", log_name)
            raise HTTPException(status_code=404, detail="경로 기록을 찾을 수 없습니다.")

        return _walk_progress_response(history)
    except HTTPException:
        raise
    except Exception as e:
        log_unexpected_error(logger, f"{log_name}_unexpected_error", e)
        raise HTTPException(status_code=500, detail=SAFE_INTERNAL_ERROR_DETAIL) from e


@router.post("/routes/{history_id}/start", response_model=RouteWalkProgressResponse)
def start_route_walk(
    history_id: int,
    access_token: str | None = Depends(resolve_access_token),
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    산책 시작을 누른 경로로 기록합니다. 요청 본문은 없고, 바로 진행 중(in_progress)으로 바뀝니다.
    응답 walk_status는 처리 후 진행 상태입니다. 이미 진행 중이거나 완주한 경로를 다시 호출해도
    상태를 되돌리지 않습니다.
    """
    return _update_walk_progress(
        history_id, access_token, auth_service, RouteHistoryRepository.mark_started, "route_walk_start",
    )


@router.post("/routes/{history_id}/complete", response_model=RouteWalkProgressResponse)
def complete_route_walk(
    history_id: int,
    access_token: str | None = Depends(resolve_access_token),
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    완주를 기록합니다. 요청 본문은 없고, 호출되면 무조건 완주(completed)로 기록하며 완주한 날짜
    (한국 시간 기준)를 walked_on에 저장합니다. 산책을 중간에 끝낸 경우에는 호출하지 않으며,
    이 경우 경로는 in_progress로 남습니다. 이미 완주한 경로를 다시 호출해도 날짜는 바뀌지 않습니다.
    """
    return _update_walk_progress(
        history_id, access_token, auth_service, RouteHistoryRepository.mark_completed, "route_walk_complete",
    )


@router.get("/routes/{history_id}", response_model=RouteHistoryItem)
def get_route_history(
    history_id: int,
    access_token: str | None = Depends(resolve_access_token),
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    특정 추천 경로 기록 상세를 조회합니다.
    """
    try:
        status, provider, provider_id = auth_service.check_access_token(
            access_token
        )
        if status != Status.SUCCESS:
            logger.warning("route_history_detail_auth_failed | status=%s", status.value)
            raise HTTPException(status_code=401, detail=status.value)

        user = UserRepository.find_by_provider_and_provider_id(provider, provider_id)
        if user is None:
            logger.warning("route_history_detail_user_not_found")
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

        history = RouteHistoryRepository.find_by_id(history_id, user.id)
        if history is None:
            logger.warning("route_history_detail_not_found")
            raise HTTPException(status_code=404, detail="경로 기록을 찾을 수 없습니다.")

        return RouteHistoryItem.model_validate(history)
    except HTTPException:
        raise
    except Exception as e:
        log_unexpected_error(logger, "route_history_detail_unexpected_error", e)
        raise HTTPException(status_code=500, detail=SAFE_INTERNAL_ERROR_DETAIL) from e


@router.post("/routes/{history_id}/feedback", response_model=RouteFeedbackResponse)
def submit_route_feedback(
    history_id: int,
    request: RouteFeedbackRequest,
    access_token: str | None = Depends(resolve_access_token),
    service: LongTermProfileService = Depends(get_longterm_profile_service),
):
    """
    산책 후 피드백(안전/편안/전체 별점, 각 1~5, 선택 입력)을 제출합니다. 비어 있는 별점은 3점(중립)으로
    간주하고, 세 별점이 모두 비어 있으면 저장·학습 없이 현재 가중치를 돌려줍니다.
    순환과 편도 우회 경로의 피드백만 장기 프로필을 갱신하고(최단 경로 등은 별점만 저장),
    후보 경로가 있으면 대표 경로와 대조(contrast)해, 없으면 별점만으로 장기 프로필
    (weights_safety/weights_comfort)이 온라인 SGD로 갱신됩니다 — longterm_profile_service 참고.
    """
    return service.submit_feedback(
        access_token, history_id, request
    )


@router.get("/survey", response_model=SurveyStatusResponse)
def get_survey_status(
    access_token: str | None = Depends(resolve_access_token),
    service: SurveyService = Depends(get_survey_service),
):
    """설문 완료 여부를 반환합니다."""
    return service.get_status(access_token)
