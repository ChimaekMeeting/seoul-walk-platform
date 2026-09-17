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
from src.schema.route_schema import Weights


# 2026-09-17: 온보딩/챗봇 테마 태그가 "안전"/"편안" 둘로 통일되면서, 여러 키워드가
# 각자 델타를 더하던 예전 방식(나무 많은/유모차/활기찬 등 20여 개 태그)을 걷어냈다.
# extractor.py(대화에서 테마 태그 추출)/route_executor.py(태그별 가중치 EMA 블렌딩)도
# 이 딕셔너리 키 집합을 그대로 참조하므로 두 축만 남는다.
TAG_WEIGHT_MAP: dict[str, dict[str, float]] = {
    "안전": {"safety":  +0.2},
    "편안": {"comfort": +0.2},
}

DISTANCE_MAP: dict[DistanceOption, float] = {
    DistanceOption.SLOW:   2.0,
    DistanceOption.NORMAL: 3.0,
    DistanceOption.FAST:   5.0,
}

# 설문 가중치 baseline은 route_schema.Weights 기본값을 단일 출처(SSOT)로 사용함.
#   (안전/평지 0.5, 미관·활동·동반 0.0 → 안 고른 특성은 무편향)
BASE_WEIGHTS: dict[str, float] = Weights().model_dump()

# 편안(comfort)은 Weights(route_schema)에 없는 축이라 별도 baseline을 둔다.
# 0.0(무편향)에서 시작 — TAG_WEIGHT_MAP과 달리 comfort는
# _safety_comfort_deltas()의 k 배분 공식으로만 초기값이 정해진다.
BASE_COMFORT: float = 0.0

# --- 온보딩 "안전"/"편안" 버튼 선택 조합 → γ(안전)/β(편안) 배분 공식 ---
# 장기 프로필이 실제로 추적하는 두 축(안전/편안)의 초기값을 이 공식 하나로 정한다 —
# weights_safety는 더 이상 TAG_WEIGHT_MAP 태그 델타가 아니라 이 공식에서만 나온다.
# k: 두 축에 배분할 총 예산. d: 선택 안 한 축도 갖는 최소 바닥값(무편향 방지용).
# r: 선택된 축에 추가로 쏠리는 몫. r = k - 2d.
#   둘 다 선택   → γ=β=k/2                 (예: k=0.3 → 0.15/0.15)
#   하나만 선택  → 선택된 축=r+d, 나머지=d  (예: 0.267/0.033)
#   둘 다 미선택 → γ=β=d                   (예: 0.033/0.033, 합=2d)
_SAFETY_COMFORT_K: float = 0.3
_SAFETY_COMFORT_D: float = _SAFETY_COMFORT_K / 9


def _safety_comfort_deltas(selected_safety: bool, selected_comfort: bool) -> tuple[float, float]:
    """온보딩 안전/편안 선택 조합으로 (γ_안전, β_편안) 가중치 델타를 계산합니다."""
    k, d = _SAFETY_COMFORT_K, _SAFETY_COMFORT_D
    r = k - 2 * d
    if selected_safety and selected_comfort:
        return k / 2, k / 2
    if selected_safety:
        return r + d, d
    if selected_comfort:
        return d, r + d
    return d, d

# 온보딩 설문 UI에 노출할 태그 목록. TAG_WEIGHT_MAP과 동일(안전/편안 둘뿐).
SURVEY_TAGS: list[str] = ["안전", "편안"]

class SurveyService:
    """
    온보딩 설문 제출을 처리하는 서비스입니다.
    """

    def __init__(self, auth_service: AuthService):
        self.auth_service = auth_service

    def submit(self, access_token: str | None, request: SurveyRequest) -> SurveyResponse:
        """
        설문 결과를 장기 프로필(weights_safety/weights_comfort)의 초기값으로 변환해
        UserPreference에 저장합니다.

        두 축 다 request.tags에 "안전"/"편안"이 포함됐는지로 _safety_comfort_deltas()가
        계산한 (γ_안전, β_편안) 델타를 각각의 baseline(안전 0.5, 편안 0.0)에 더해
        정합니다 — TAG_WEIGHT_MAP은 안전/편안 +0.2 델타만 갖고 있을 뿐 이 계산에는
        쓰이지 않습니다(장기 프로필 초기값은 이 공식 하나로만 정해짐). tags는
        selected_tags로 참고용으로만 그대로 저장됩니다. TAG_WEIGHT_MAP은 챗봇 테마
        추출(extractor.py)/가중치 블렌딩(route_executor.py)이 안전/편안 두 키로만
        참조합니다.
        최종값은 [0.0, 1.0]으로 클램핑됩니다.
        """

        status, provider, provider_id = self.auth_service.check_access_token(access_token)
        if status != Status.SUCCESS:
            return SurveyResponse(status=status)

        user = UserRepository.find_by_provider_and_provider_id(provider, provider_id)
        if user is None:
            return SurveyResponse(status=SurveyStatus.USER_NOT_FOUND)

        safety_delta, comfort_delta = _safety_comfort_deltas(
            selected_safety="안전" in request.tags,
            selected_comfort="편안" in request.tags,
        )
        weights_safety = max(0.0, min(1.0, BASE_WEIGHTS["safety"] + safety_delta))
        weights_comfort = max(0.0, min(1.0, BASE_COMFORT + comfort_delta))

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
        """사용자의 설문 완료 여부와 저장된 장기 프로필(안전/편안 가중치)을 반환합니다."""
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
