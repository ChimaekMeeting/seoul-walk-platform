"""
src/service/user/longterm_profile_service.py

3단계 — 산책 후 피드백 기반 장기 프로필 갱신 (온라인 선형회귀 / SGD).

세션 가중치 EMA와 달리, 사용자가 실제로 그 길을 걷고 별점(안전/편안/전체, 각 1~5)을
남긴 뒤에만 UserPreference.weights_safety/weights_comfort(장기 프로필)를 갱신한다.

오귀속 방지(anti-misattribution):
    서울 도보 경로는 인프라 특성상 대부분 구간에서 '안전' 기본 점수가 이미 높다.
    선택 경로의 특성값(X_R)을 그대로 쓰면 "예쁜 자연 풍경"에 만족해서 준 별점이
    이미 높았던 안전 점수까지 함께 끌어올리는 왜곡이 생긴다. 이를 막기 위해 마지막까지
    경합한 후보 경로들과의 차이값(contrast)만 학습 입력으로 쓴다:

        X_contrast,i = X_R,i - mean(X_candidates,i)   (i = safety, comfort)

    특성값은 탐색 비용식과 같은 지표다 — safety = 1 - unsafe, comfort = 1 - discomfort
    (scoring_engine.path_feature_averages). 학습된 가중치가 비용식에서 alpha * unsafe,
    beta * discomfort로 쓰이므로 입력도 같은 지표여야 한다.

    X_R은 대표 후보(사용자에게 보여준/걸은 경로), X_candidates는 같은 요청에서 함께
    생성됐지만 보여주지 않은 나머지 후보(RouteService가 최소 2개를 보장 — route_service.
    MIN_CANDIDATES_FOR_PROFILE)다. 대표 후보 자신은 mean에서 제외한다 — 대조는 "내가
    고르지 않은 것들과 얼마나 달랐는가"를 봐야지, 자기 자신을 섞으면 대조가 희석된다.

표준 SGD 갱신 규칙: W <- W + η(y - ŷ)X
    각 차원(safety/comfort)마다 두 스텝을 순서대로 적용한다.
    1) 자기 축 스텝 — 그 축 자신의 별점으로 그 축의 가중치만 갱신.
       ŷ_d = 0.5 + W_d * X_contrast,d,  W_d += η(y_d - ŷ_d) X_contrast,d
    2) 전체 별점 결합 스텝 — 안전/편안 두 축이 함께 "전체 만족도"를 설명하도록,
       전체 별점 오차를 두 축에 동시에 흘려보낸다(선형회귀 W·X_contrast의 표준형).
       ŷ_overall = 0.5 + mean_d(W_d * X_contrast,d)
       W_d += η(y_overall - ŷ_overall) X_contrast,d
    세 별점(안전/편안/전체) 모두를 입력으로 요구하는 이유이자, W가 정확히 2차원
    (safety, comfort)인 이유다 — user_preference.py의 장기 프로필 범위 축소 참고.

적응형 학습률: 서비스 초기(feedback_count 적음)에는 η를 크게, 누적될수록 줄여
    한두 번의 특이 평가로 프로필이 급변하지 않게 한다.

갱신 폭 상한(#487): X_contrast를 ±_CONTRAST_CAP으로 제한한다(부호는 유지, 크기만 제한).
    한 번의 피드백이 가중치를 크게 흔들지 못하게 하려는 안전장치다.

온보딩 초기값 하한(#487): 갱신된 가중치는 온보딩 설문이 정한 초기값 아래로 내려가지 않는다
    (_onboarding_initial_weights). 설문을 안 한 사용자는 기본값(safety=0.5, comfort=0.0)이 하한이다.
"""
import logging

from src.entity.route_feedback import RouteFeedback
from src.entity.route_history import RouteHistory
from src.interfaces.schema.auth_schema import Status
from src.interfaces.schema.route_feedback_schema import (
    RouteFeedbackRequest,
    RouteFeedbackResponse,
    RouteFeedbackStatus,
)
from src.repository.user.route_feedback_repository import RouteFeedbackRepository
from src.repository.user.route_history_repository import RouteHistoryRepository
from src.repository.user.user_preference_repository import UserPreferenceRepository
from src.repository.user.user_repository import UserRepository
from src.route_engine.scoring.scoring_engine import FEATURE_DIMENSIONS
from src.service.route.route_service import MIN_CANDIDATES_FOR_PROFILE
from src.service.user.auth_service import AuthService
from src.service.user.survey_service import BASE_COMFORT, BASE_WEIGHTS, _safety_comfort_deltas

logger = logging.getLogger(__name__)

# η(t) = max(MIN_LR, INITIAL_LR / (1 + DECAY_RATE * feedback_count))
INITIAL_LR = 0.5
DECAY_RATE = 0.5
MIN_LR = 0.05

# X_contrast의 크기 상한(#487). "한 번의 피드백에서 가중치를 최대 얼마나 움직이게 할지"로 정한 값이며
# 0.1이면 첫 피드백 기준 최대 약 ±0.055다(피드백이 쌓일수록 η가 줄어 더 작아진다).
_CONTRAST_CAP = 0.1

_NEUTRAL_PREDICTION = 0.5  # ŷ의 중심값 — X_contrast=0(모든 후보가 특성상 동일)이면 예측은 "평범"


def _normalize_rating(rating: int) -> float:
    """1~5 별점을 [0.0, 1.0]로 정규화합니다."""
    return (rating - 1) / 4.0


def _adaptive_learning_rate(feedback_count: int) -> float:
    return max(MIN_LR, INITIAL_LR / (1 + DECAY_RATE * feedback_count))


def _onboarding_initial_weights(preference) -> dict[str, float]:
    """온보딩 설문이 정한 가중치 초기값 — SGD 갱신 결과의 하한이다(#487).

    survey_service.submit()과 같은 식으로 selected_tags("안전"/"편안" 선택 조합)에서 다시 계산한다.
    설문을 하지 않은 사용자(행이 없거나 survey_completed가 아님)는 기본값(safety=0.5, comfort=0.0)이다.
    selected_tags가 없는 설문 완료 행은 "둘 다 미선택"으로 본다.
    """
    if preference is None or getattr(preference, "survey_completed", False) is not True:
        return {"safety": BASE_WEIGHTS["safety"], "comfort": BASE_COMFORT}

    tags = preference.selected_tags or []
    safety_delta, comfort_delta = _safety_comfort_deltas(
        selected_safety="안전" in tags,
        selected_comfort="편안" in tags,
    )
    return {
        "safety": max(0.0, min(1.0, BASE_WEIGHTS["safety"] + safety_delta)),
        "comfort": max(0.0, min(1.0, BASE_COMFORT + comfort_delta)),
    }


def _contrast_vector(candidate_features: list[dict[str, float]]) -> dict[str, float]:
    """X_contrast,i = X_R,i - mean(X_candidates,i). candidate_features[0]가 대표 후보(X_R)다."""
    chosen = candidate_features[0]
    others = candidate_features[1:]
    n = len(others)
    return {
        dim: chosen.get(dim, 0.0) - sum(o.get(dim, 0.0) for o in others) / n
        for dim in FEATURE_DIMENSIONS
    }


class LongTermProfileService:
    """
    산책 후 피드백을 받아 장기 프로필(안전/편안 가중치)을 온라인 SGD로 갱신하는 서비스입니다.
    """

    def __init__(self, auth_service: AuthService):
        self.auth_service = auth_service

    def submit_feedback(
        self,
        access_token: str | None,
        route_history_id: int,
        request: RouteFeedbackRequest,
    ) -> RouteFeedbackResponse:
        status, provider, provider_id = self.auth_service.check_access_token(access_token)
        if status != Status.SUCCESS:
            return RouteFeedbackResponse(status=RouteFeedbackStatus(status.value))

        user = UserRepository.find_by_provider_and_provider_id(provider, provider_id)
        if user is None:
            return RouteFeedbackResponse(status=RouteFeedbackStatus.USER_NOT_FOUND)

        history = RouteHistoryRepository.find_by_id(route_history_id, user.id)
        if history is None:
            return RouteFeedbackResponse(status=RouteFeedbackStatus.ROUTE_NOT_FOUND)

        # 별점 자체는 항상 저장한다 — 장기 프로필 갱신 가능 여부와 무관하게 기록으로 남긴다.
        # 다만 같은 route_history_id의 재제출은 기존 별점 수정일 뿐 새 산책 경험이 아니다.
        # 이미 학습한 경로를 다시 SGD에 넣으면 feedback_count와 가중치가 중복 누적되므로,
        # 최초 제출인지 먼저 기억해 두고 재제출은 저장만 한 뒤 현재 가중치를 반환한다.
        existing_feedback = RouteFeedbackRepository.find_by_route_history_id(route_history_id)
        RouteFeedbackRepository.upsert(
            user_id=user.id,
            route_history_id=route_history_id,
            rating_safety=request.rating_safety,
            rating_comfort=request.rating_comfort,
            rating_overall=request.rating_overall,
        )

        candidate_features = history.candidate_features
        if not candidate_features or len(candidate_features) < MIN_CANDIDATES_FOR_PROFILE:
            logger.info(
                "longterm profile update skipped — insufficient candidates: "
                "route_history_id=%d count=%d",
                route_history_id, len(candidate_features or []),
            )
            preference = UserPreferenceRepository.get_by_user_id(user.id)
            return RouteFeedbackResponse(
                status=RouteFeedbackStatus.INSUFFICIENT_CANDIDATES,
                weights_safety=preference.weights_safety if preference else None,
                weights_comfort=preference.weights_comfort if preference else None,
            )

        if existing_feedback is not None:
            preference = UserPreferenceRepository.get_by_user_id(user.id)
            return RouteFeedbackResponse(
                status=RouteFeedbackStatus.SUCCESS,
                weights_safety=preference.weights_safety if preference else None,
                weights_comfort=preference.weights_comfort if preference else None,
            )

        weights_safety, weights_comfort = self._apply_sgd_update(
            user_id=user.id,
            candidate_features=candidate_features,
            rating_safety=request.rating_safety,
            rating_comfort=request.rating_comfort,
            rating_overall=request.rating_overall,
        )

        return RouteFeedbackResponse(
            status=RouteFeedbackStatus.SUCCESS,
            weights_safety=weights_safety,
            weights_comfort=weights_comfort,
        )

    def _apply_sgd_update(
        self,
        user_id: int,
        candidate_features: list[dict[str, float]],
        rating_safety: int,
        rating_comfort: int,
        rating_overall: int,
    ) -> tuple[float, float]:
        preference = UserPreferenceRepository.get_by_user_id(user_id)
        weights = {
            "safety": (preference.weights_safety if preference and preference.weights_safety is not None
                       else BASE_WEIGHTS["safety"]),
            "comfort": (preference.weights_comfort if preference and preference.weights_comfort is not None
                        else BASE_COMFORT),
        }
        # NULL 가능성: init_table()의 ADD COLUMN은 기존 행을 백필하지 않아, 이 컬럼이 생기기
        # 전부터 있던 UserPreference 행은 feedback_count가 DB상 NULL일 수 있다(컬럼 자체의
        # nullable=False는 SQLAlchemy 모델 선언일 뿐, 기존 행에 소급 적용되지 않는다).
        feedback_count = (
            preference.feedback_count if preference and preference.feedback_count is not None else 0
        )

        x_contrast = _contrast_vector(candidate_features)
        # 갱신 폭 상한(#487): 부호는 유지하고 크기만 ±_CONTRAST_CAP으로 제한한다.
        x_contrast = {dim: max(-_CONTRAST_CAP, min(_CONTRAST_CAP, v)) for dim, v in x_contrast.items()}

        eta = _adaptive_learning_rate(feedback_count)

        y = {
            "safety": _normalize_rating(rating_safety),
            "comfort": _normalize_rating(rating_comfort),
        }
        y_overall = _normalize_rating(rating_overall)

        # 1) 자기 축 스텝 — 각 축을 그 축 자신의 별점으로 갱신.
        for dim in FEATURE_DIMENSIONS:
            y_hat = _NEUTRAL_PREDICTION + weights[dim] * x_contrast[dim]
            weights[dim] += eta * (y[dim] - y_hat) * x_contrast[dim]

        # 2) 전체 별점 결합 스텝 — 두 축이 함께 전체 만족도를 설명하도록 결합 오차를 분배.
        y_hat_overall = _NEUTRAL_PREDICTION + sum(
            weights[dim] * x_contrast[dim] for dim in FEATURE_DIMENSIONS
        ) / len(FEATURE_DIMENSIONS)
        overall_error = y_overall - y_hat_overall
        for dim in FEATURE_DIMENSIONS:
            weights[dim] += eta * overall_error * x_contrast[dim]

        # 온보딩 초기값 하한(#487): 상한은 1.0, 하한은 온보딩 초기값(0.0 이상)이다.
        initial = _onboarding_initial_weights(preference)
        weights = {dim: max(initial[dim], min(1.0, value)) for dim, value in weights.items()}

        updated = UserPreferenceRepository.upsert(
            user_id=user_id,
            weights_safety=weights["safety"],
            weights_comfort=weights["comfort"],
            feedback_count=feedback_count + 1,
        )
        return updated.weights_safety, updated.weights_comfort
