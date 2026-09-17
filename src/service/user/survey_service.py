"""
src/service/user/survey_service.py

온보딩 설문 비즈니스 로직을 담당하는 서비스.
키워드 태그를 경로 가중치로 변환하고 UserPreference에 저장한다.
"""
from src.interfaces.schema.auth_schema import Status
from src.repository.user.user_preference_repository import UserPreferenceRepository
from src.repository.user.user_repository import UserRepository
from src.service.user.auth_service import AuthService
from src.interfaces.schema.survey_schema import DistanceOption, SurveyRequest, SurveyResponse, SurveyStatus, SurveyStatusResponse


# 2026-09-17: FE가 보내는 온보딩 태그는 이제 "안전"·"편안" 둘뿐이라, 여러 키워드가
# 델타를 더하던 기존 방식을 걷어내고 태그 하나 = 축 하나로 단순화했다. "slope"라는
# route_schema.Weights 필드명은 route_executor에서 Weights(**...)를 만들 때만 쓰고,
# 그 전 단계(TAG_WEIGHT_MAP·BASE_WEIGHTS·UserPreference 컬럼)는 전부 "comfort"로
# 통일한다.
TAG_WEIGHT_MAP: dict[str, dict[str, float]] = {
    "안전": {"safety":      +0.2},
    "편안": {"comfort": +0.2},
}

DISTANCE_MAP: dict[DistanceOption, float] = {
    DistanceOption.SLOW:   2.0,
    DistanceOption.NORMAL: 3.0,
    DistanceOption.FAST:   5.0,
}

# safety/comfort의 중립 baseline. route_schema.Weights의 safety/slope 기본값(0.5)과
# 같은 값이지만, 이 서비스 레이어에서는 "slope"라는 이름을 쓰지 않는다.
BASE_WEIGHTS: dict[str, float] = {
    "safety":  0.5,
    "comfort": 0.5,
}

# 온보딩 설문 UI에 노출할 태그 목록. TAG_WEIGHT_MAP의 부분집합.
SURVEY_TAGS: list[str] = ["안전", "편안"]

class SurveyService:
    """
    온보딩 설문 제출을 처리하는 서비스입니다.
    """

    def __init__(self, auth_service: AuthService):
        self.auth_service = auth_service

    def submit(self, access_token: str | None, request: SurveyRequest) -> SurveyResponse:
        """
        설문 결과를 가중치로 변환해 UserPreference에 저장합니다.

        BASE_WEIGHTS(safety/comfort 0.5)에서 시작하며, "안전"/"편안" 태그가
        각각 safety/comfort delta를 더합니다. 최종값은 [0.0, 1.0]으로 클램핑됩니다.
        """

        status, provider, provider_id = self.auth_service.check_access_token(access_token)
        if status != Status.SUCCESS:
            return SurveyResponse(status=status)

        user = UserRepository.find_by_provider_and_provider_id(provider, provider_id)
        if user is None:
            return SurveyResponse(status=SurveyStatus.USER_NOT_FOUND)
        
        weights = dict(BASE_WEIGHTS)
        for tag in request.tags:
            for key, delta in TAG_WEIGHT_MAP.get(tag, {}).items():
                weights[key] = max(0.0, min(1.0, weights[key] + delta))

        preference = UserPreferenceRepository.upsert(
            user_id=user.id,
            survey_completed=True,
            default_target_km=DISTANCE_MAP.get(request.distance) if request.distance else None,
            weights_safety=weights.get("safety"),
            weights_comfort=weights.get("comfort"),
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
