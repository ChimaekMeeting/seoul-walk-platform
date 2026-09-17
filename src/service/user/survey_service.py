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


TAG_WEIGHT_MAP: dict[str, dict[str, float]] = {
    # nature: 자연 친화도
    "나무 많은":     {"nature":   +0.2},
    "꽃길":          {"nature":   +0.2},
    "햇살 좋은":     {"nature":   +0.2},
    "그늘이 많은":   {"nature":   +0.1},

    # safety: 안전성 (조용하거나 골목길은 안전 가중치 하향 또는 분리)
    "밤에도 안전한": {"safety":   +0.2},
    "큰길":          {"safety":   +0.2},
    "밝은 길":       {"safety":   +0.2},
    "골목골목":      {"safety":  -0.1},

    # slope & running: 경사도 및 활동성
    "숨 안 차는":    {"slope":    +0.3}, # 평지 선호 (상승고도 회피)
    "평탄한":        {"slope":    +0.2},
    "뛰고 싶은":     {"running":  +0.2, "slope":  -0.1}, # 경사 수용, 러닝 적합
    "운동":         {"running":  +0.2, "slope":  -0.2}, # 가파른 경사도 수용

    # landmark: 볼거리 및 혼잡도
    "볼거리 많은":   {"landmark": +0.2},
    "인스타 감성":   {"landmark": +0.2},
    "조용한":       {"landmark": -0.2, "safety":  -0.1}, # 한적하지만 인적이 드물 수 있음
    "야경이 예쁜":   {"landmark": +0.2, "safety":  +0.1},  # 야간 안전 확보된 명소

    # 동반자 중심 복합 필터
    "어린이":       {"child": +0.2, "slope": +0.1},
    "반려동물":     {"nature": +0.1},
    "유모차":       {"child": +0.1, "slope": +0.3, "safety": +0.1, "accessibility": +0.3},
    "계단이 불편한": {"slope": +0.3, "safety": +0.1, "accessibility": +0.4},

    # 감성 / 분위기 (Mood)
    "활기찬":        {"landmark": +0.2, "safety": +0.1, "convenience": +0.2},
    "사색하기 좋은":  {"landmark": -0.2, "slope":   +0.1},  # 조용하고 평탄하여 걷기 좋은 길
    "힙한":          {"landmark": +0.25, "convenience": +0.25},

    # 색상 / 시각적 이미지 (Visual Color)
    "노랑":          {"nature":   +0.15, "landmark": +0.1}, # 따뜻함, 은행나무, 봄꽃, 조명
    "분홍":          {"nature":   +0.25, "landmark": +0.1}, # 벚꽃길, 장미터널 등 개화 시기 저격
    "파랑":          {"nature": +0.1},                      # 청량함, 한강변, 호수공원, 해안도로
    "초록":          {"nature":   +0.3}                     # 숲길, 대형 공원 등 자연 극대화
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

# 온보딩 설문 UI에 노출할 태그 목록. TAG_WEIGHT_MAP의 부분집합.
SURVEY_TAGS: list[str] = [
    "나무 많은", "꽃길", "초록",
    "밤에도 안전한", "큰길",
    "숨 안 차는", "뛰고 싶은", "운동",
    "볼거리 많은", "야경이 예쁜", "힙한",
    "조용한", "활기찬",
    "어린이", "반려동물", "유모차", "계단이 불편한",
]

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
        정합니다 — 지금 프론트가 보내는 온보딩 태그는 "안전"/"편안" 이 둘뿐이라,
        기존 TAG_WEIGHT_MAP의 세부 태그 델타(±0.2 등)는 더 이상 weights_safety/
        weights_comfort에 반영되지 않습니다(장기 프로필이 추적하는 축이 정확히 이
        두 개라서 온보딩 초기값도 이 공식 하나로 통일함). tags는 selected_tags로
        참고용으로만 그대로 저장됩니다. TAG_WEIGHT_MAP 자체는 챗봇 테마 추출
        (extractor.py)/가중치 블렌딩(route_executor.py)이 여전히 쓰므로 그대로 둔다.
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
