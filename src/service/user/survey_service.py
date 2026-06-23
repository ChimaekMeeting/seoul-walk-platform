"""
src/service/user/survey_service.py

온보딩 설문 비즈니스 로직을 담당하는 서비스.
키워드 태그를 경로 가중치로 변환하고 UserPreference에 저장한다.
"""
from src.interfaces.schema.auth_schema import Status
from src.interfaces.schema.survey_schema import DistanceOption, SurveyRequest, SurveyResponse, SurveyStatus
from src.repository.user.user_preference_repository import UserPreferenceRepository
from src.repository.user.user_repository import UserRepository
from src.service.user.auth_service import AuthService

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
    "어린이":       {"child":    +0.2, "slope":  +0.1},  # 평지 선호 포함
    "반려동물":     {"nature":   +0.1, "child":  +0.1},
    "유모차":       {"child":    +0.1, "slope":    +0.3, "safety": +0.1},
    "휠체어":       {"slope":    +0.3, "safety": +0.1},   # 계단 및 경사 절대 회피

    # 감성 / 분위기 (Mood)
    "활기찬":        {"landmark": +0.2, "safety":  +0.1},  # 유동인구가 많고 활력 있는 길
    "사색하기 좋은":  {"landmark": -0.2, "slope":   +0.1},  # 조용하고 평탄하여 걷기 좋은 길
    "힙한":          {"landmark": +0.25},  # 트렌디한 상권이나 팝업스토어 주변

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

BASE_WEIGHTS: dict[str, float] = {
    "safety":   0.5,
    "nature":   0.5,
    "slope":    0.5,
    "running":  0.5,
    "landmark": 0.5,
    "child":    0.5,
}

# 온보딩 설문 UI에 노출할 태그 목록. TAG_WEIGHT_MAP의 부분집합.
SURVEY_TAGS: list[str] = [
    "나무 많은", "꽃길", "초록",
    "밤에도 안전한", "큰길",
    "숨 안 차는", "뛰고 싶은", "운동",
    "볼거리 많은", "야경이 예쁜", "힙한",
    "조용한", "활기찬",
    "어린이", "반려동물",
]

class SurveyService:
    """
    온보딩 설문 제출을 처리하는 서비스입니다.
    """

    def __init__(self, auth_service: AuthService):
        self.auth_service = auth_service

    def submit(self, access_token: str | None, request: SurveyRequest) -> SurveyResponse:
        """
        설문 결과를 가중치로 변환해 UserPreference에 저장합니다.

        모든 가중치는 0.5에서 시작하며, 각 태그는 TAG_WEIGHT_MAP의 delta(±0.2)로 조정됩니다.
        최종값은 [0.0, 1.0]으로 클램핑됩니다.
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
            weights_nature=weights.get("nature"),
            weights_slope=weights.get("slope"),
            weights_running=weights.get("running"),
            weights_landmark=weights.get("landmark"),
            weights_child=weights.get("child"),
        )

        return SurveyResponse(
            status=SurveyStatus.SUCCESS,
            default_target_km=preference.default_target_km,
            weights_safety=preference.weights_safety,
            weights_nature=preference.weights_nature,
            weights_slope=preference.weights_slope,
            weights_running=preference.weights_running,
            weights_landmark=preference.weights_landmark,
            weights_child=preference.weights_child,
        )
