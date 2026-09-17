"""
src/service/user/survey_service.py

온보딩 설문 비즈니스 로직을 담당하는 서비스.
사용자가 선택한 안전·편안 여부를 가중치로 변환해 UserPreference에 저장한다.
"""
from src.interfaces.schema.auth_schema import Status
from src.repository.user.user_preference_repository import UserPreferenceRepository
from src.repository.user.user_repository import UserRepository
from src.service.user.auth_service import AuthService
from src.interfaces.schema.survey_schema import DistanceOption, SurveyRequest, SurveyResponse, SurveyStatus, SurveyStatusResponse


DISTANCE_MAP: dict[DistanceOption, float] = {
    DistanceOption.SLOW:   2.0,
    DistanceOption.NORMAL: 3.0,
    DistanceOption.FAST:   5.0,
}

# 안전·편안 2축 가중치 배분 계수(세은 담당, 장기 프로필 갱신 스킴).
#   k=0.3, d=k/9 — 두 축 다 선택 시 절반씩(k/2), 하나만 선택 시 그 축은 k-d·나머지는 d,
#   둘 다 선택 안 하면 둘 다 d.
_K = 0.3
_D = round(_K / 9, 4)      # 0.0333 — 선택 안 한 축
_HIGH = round(_K - _D, 4)  # 0.2667 — 그 축만 선택
_HALF = round(_K / 2, 4)   # 0.15   — 두 축 다 선택


def _resolve_weights(safety: bool, comfort: bool) -> tuple[float, float]:
    """안전·편안 선택 여부로 (weights_safety, weights_comfort)를 고정값에서 조회합니다."""
    if safety and comfort:
        return _HALF, _HALF
    if safety:
        return _HIGH, _D
    if comfort:
        return _D, _HIGH
    return _D, _D


class SurveyService:
    """
    온보딩 설문 제출을 처리하는 서비스입니다.
    """

    def __init__(self, auth_service: AuthService):
        self.auth_service = auth_service

    def submit(self, access_token: str | None, request: SurveyRequest) -> SurveyResponse:
        """
        설문 결과(안전·편안 선택 여부)를 가중치로 변환해 UserPreference에 저장합니다.
        """

        status, provider, provider_id = self.auth_service.check_access_token(access_token)
        if status != Status.SUCCESS:
            return SurveyResponse(status=status)

        user = UserRepository.find_by_provider_and_provider_id(provider, provider_id)
        if user is None:
            return SurveyResponse(status=SurveyStatus.USER_NOT_FOUND)

        safety_selected = "safety" in request.tags
        comfort_selected = "comfort" in request.tags
        weights_safety, weights_comfort = _resolve_weights(safety_selected, comfort_selected)

        preference = UserPreferenceRepository.upsert(
            user_id=user.id,
            survey_completed=True,
            default_target_km=DISTANCE_MAP.get(request.distance) if request.distance else None,
            weights_safety=weights_safety,
            weights_comfort=weights_comfort,
            selected_tags=request.tags if request.tags else None,
        )

        return SurveyResponse(
            status=SurveyStatus.SUCCESS,
            default_target_km=preference.default_target_km,
            weights_safety=preference.weights_safety,
            weights_comfort=preference.weights_comfort,
        )

    def get_status(self, access_token: str | None) -> SurveyStatusResponse:
        """사용자의 설문 완료 여부와 저장된 가중치를 반환합니다."""
        status, provider, provider_id = self.auth_service.check_access_token(access_token)
        if status != Status.SUCCESS:
            return SurveyStatusResponse(status=SurveyStatus(status.value), survey_completed=False)

        user = UserRepository.find_by_provider_and_provider_id(provider, provider_id)
        if user is None:
            return SurveyStatusResponse(status=SurveyStatus.USER_NOT_FOUND, survey_completed=False)

        preference = UserPreferenceRepository.get_by_user_id(user.id)
        if preference is None or not preference.survey_completed:
            return SurveyStatusResponse(status=SurveyStatus.SUCCESS, survey_completed=False)

        return SurveyStatusResponse(
            status=SurveyStatus.SUCCESS,
            survey_completed=True,
            default_target_km=preference.default_target_km,
            weights_safety=preference.weights_safety,
            weights_comfort=preference.weights_comfort,
            selected_tags=preference.selected_tags,
        )


# 임시 호환용 — route_executor.py, extractor.py가 이 이름을 import함.
# 실제로는 더 이상 안 쓰임(_resolve_weights가 대체). 알고리즘/챗봇 팀이
# 이 import를 제거하면 이 줄도 지워도 됨.
TAG_WEIGHT_MAP: dict = {}
