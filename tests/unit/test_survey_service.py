"""
tests/unit/test_survey_service.py
SurveyService 단위 테스트

장기 프로필 범위 축소(2026-09, user_preference.py 참고)로 영속 필드가
weights_safety/weights_comfort/default_target_km/selected_tags로 줄었다.
weights_safety/weights_comfort는 둘 다 request.tags에 "안전"/"편안"이 포함됐는지로
γ(안전)/β(편안) 배분 공식(_safety_comfort_deltas) 하나로만 정해진다 — 지금 프론트가
보내는 온보딩 태그는 "안전"/"편안" 이 둘뿐이며, 기존 TAG_WEIGHT_MAP의 세부 태그
델타(±0.2 등)는 더 이상 weights_safety/weights_comfort에 반영되지 않는다(선택한
태그는 selected_tags 컬럼에 참고용으로만 저장됨). TAG_WEIGHT_MAP 자체는 챗봇
테마 추출/가중치 블렌딩(extractor.py, route_executor.py)이 여전히 쓰므로 그대로 둔다.

검증 항목:
  - 인증 실패 시 status 반환
  - 사용자 미존재 시 USER_NOT_FOUND 반환
  - tags에 "안전"/"편안" 포함 조합 → γ/β 배분 공식(_safety_comfort_deltas)
  - 그 외 세부 태그는 더 이상 weights_safety/weights_comfort에 영향을 주지 않음(회귀 가드)
  - "안전"/"편안" 태그 각각 safety/comfort에 적용
  - 동일 태그 누적, 최대값 1.0 클램핑
  - 알 수 없는 태그 무시
  - 거리 선택지 → default_target_km 매핑

2026-09-17: 온보딩 태그가 "안전"/"편안" 두 개로 단순화되면서, 그 외 축(nature 등)을
겨냥하던 케이스는 대상 태그 자체가 없어져 제거했다.
"""

import pytest
from unittest.mock import MagicMock, patch

from src.service.user.survey_service import SurveyService, _safety_comfort_deltas
from src.interfaces.schema.survey_schema import SurveyRequest, SurveyStatus, DistanceOption
from src.interfaces.schema.auth_schema import Status
from src.entity.user import Provider


# ── 픽스처 ──────────────────────────────────────────────────────────────────


@pytest.fixture
def auth_service():
    return MagicMock()


@pytest.fixture
def service(auth_service):
    return SurveyService(auth_service)


@pytest.fixture
def mock_user():
    user = MagicMock()
    user.id = 1
    return user


@pytest.fixture
def mock_preference():
    pref = MagicMock()
    pref.survey_completed = True
    pref.default_target_km = None
    pref.weights_safety = None
    pref.weights_comfort = None
    pref.feedback_count = 0
    return pref


def _submit(service, auth_service, mock_user, mock_preference, tags, distance=None):
    """설문을 제출하고 (upsert에 전달된 kwargs, SurveyResponse)를 반환하는 헬퍼."""
    auth_service.check_access_token.return_value = (Status.SUCCESS, Provider.KAKAO, "kakao-123")
    with patch(
        "src.service.user.survey_service.UserRepository.find_by_provider_and_provider_id",
        return_value=mock_user,
    ):
        with patch(
            "src.service.user.survey_service.UserPreferenceRepository.upsert",
            return_value=mock_preference,
        ) as mock_upsert:
            response = service.submit(
                "valid_token",
                SurveyRequest(tags=tags, distance=distance),
            )
            return mock_upsert.call_args.kwargs, response


def _get_upsert_kwargs(service, auth_service, mock_user, mock_preference, tags, distance=None):
    kwargs, _ = _submit(service, auth_service, mock_user, mock_preference, tags, distance=distance)
    return kwargs


# ── 인증 / 사용자 조회 실패 ───────────────────────────────────────────────────


class TestSubmitAuth:
    def test_INVALID_TOKEN이면_즉시_반환한다(self, service, auth_service):
        auth_service.check_access_token.return_value = (Status.INVALID_TOKEN, None, None)
        result = service.submit("bad_token", SurveyRequest())
        assert result.status == SurveyStatus.INVALID_TOKEN

    def test_ACCESS_EXPIRED_TOKEN이면_즉시_반환한다(self, service, auth_service):
        auth_service.check_access_token.return_value = (Status.ACCESS_EXPIRED_TOKEN, None, None)
        result = service.submit("expired_token", SurveyRequest())
        assert result.status == SurveyStatus.ACCESS_EXPIRED_TOKEN

    def test_사용자_없으면_USER_NOT_FOUND를_반환한다(self, service, auth_service):
        auth_service.check_access_token.return_value = (Status.SUCCESS, Provider.KAKAO, "kakao-123")
        with patch(
            "src.service.user.survey_service.UserRepository.find_by_provider_and_provider_id",
            return_value=None,
        ):
            result = service.submit("valid_token", SurveyRequest())
        assert result.status == SurveyStatus.USER_NOT_FOUND


# ── 안전/편안 온보딩 선택 → γ/β 배분 공식 ──────────────────────────────────────
# k=0.3, d=k/9≈0.0333, r=k-2d≈0.2333 (survey_service._safety_comfort_deltas 문서 참고)
# weights_safety = clamp(0.5 + γ), weights_comfort = clamp(0.0 + β)
# 프론트가 보내는 tags에 "안전"/"편안" 문자열이 있는지로 선택 여부를 판단한다.


class TestSafetyComfortDeltas:
    def test_둘_다_선택하면_k를_절반씩_나눈다(self):
        gamma, beta = _safety_comfort_deltas(selected_safety=True, selected_comfort=True)
        assert gamma == pytest.approx(0.15)
        assert beta == pytest.approx(0.15)

    def test_안전만_선택하면_안전이_r_plus_d를_가져간다(self):
        gamma, beta = _safety_comfort_deltas(selected_safety=True, selected_comfort=False)
        assert gamma == pytest.approx(0.2667, abs=1e-3)
        assert beta == pytest.approx(0.0333, abs=1e-3)

    def test_편안만_선택하면_편안이_r_plus_d를_가져간다(self):
        gamma, beta = _safety_comfort_deltas(selected_safety=False, selected_comfort=True)
        assert gamma == pytest.approx(0.0333, abs=1e-3)
        assert beta == pytest.approx(0.2667, abs=1e-3)

    def test_둘_다_선택_안_하면_바닥값_d만_받는다(self):
        gamma, beta = _safety_comfort_deltas(selected_safety=False, selected_comfort=False)
        assert gamma == pytest.approx(0.0333, abs=1e-3)
        assert beta == pytest.approx(0.0333, abs=1e-3)

    def test_태그가_없으면_baseline_plus_d다(
        self, service, auth_service, mock_user, mock_preference
    ):
        kwargs = _get_upsert_kwargs(service, auth_service, mock_user, mock_preference, tags=[])
        assert kwargs["weights_safety"] == pytest.approx(0.5333, abs=1e-3)   # 0.5 + d
        assert kwargs["weights_comfort"] == pytest.approx(0.0333, abs=1e-3)  # 0.0 + d
        assert set(kwargs.keys()) == {
            "user_id", "survey_completed", "default_target_km", "weights_safety",
            "weights_comfort", "selected_tags",
        }

    def test_안전_태그만_있으면_weights_safety가_크게_오른다(
        self, service, auth_service, mock_user, mock_preference
    ):
        kwargs = _get_upsert_kwargs(
            service, auth_service, mock_user, mock_preference, tags=["안전"],
        )
        assert kwargs["weights_safety"] == pytest.approx(0.7667, abs=1e-3)   # 0.5 + (r+d)
        assert kwargs["weights_comfort"] == pytest.approx(0.0333, abs=1e-3)  # 0.0 + d

    def test_편안_태그만_있으면_weights_comfort가_크게_오른다(
        self, service, auth_service, mock_user, mock_preference
    ):
        kwargs = _get_upsert_kwargs(
            service, auth_service, mock_user, mock_preference, tags=["편안"],
        )
        assert kwargs["weights_comfort"] == pytest.approx(0.2667, abs=1e-3)  # 0.0 + (r+d)
        assert kwargs["weights_safety"] == pytest.approx(0.5333, abs=1e-3)   # 0.5 + d

    def test_안전_편안_둘_다_있으면_둘_다_k_절반씩_오른다(
        self, service, auth_service, mock_user, mock_preference
    ):
        kwargs = _get_upsert_kwargs(
            service, auth_service, mock_user, mock_preference, tags=["안전", "편안"],
        )
        assert kwargs["weights_safety"] == pytest.approx(0.65, abs=1e-3)   # 0.5 + k/2
        assert kwargs["weights_comfort"] == pytest.approx(0.15, abs=1e-3)  # 0.0 + k/2

    def test_다른_세부_태그는_weights_safety_comfort에_영향을_주지_않는다(
        self, service, auth_service, mock_user, mock_preference
    ):
        # 예전엔 "밤에도 안전한" 태그가 safety +0.2를 줬지만, 지금은 tags에 정확히
        # "안전"/"편안" 문자열이 있는지만 본다 — 그 외 세부 태그는 전부 무시된다.
        with_detail_tag = _get_upsert_kwargs(
            service, auth_service, mock_user, mock_preference, tags=["밤에도 안전한"],
        )
        without_tag = _get_upsert_kwargs(
            service, auth_service, mock_user, mock_preference, tags=[],
        )
        assert with_detail_tag["weights_safety"] == pytest.approx(without_tag["weights_safety"])
        assert with_detail_tag["weights_comfort"] == pytest.approx(without_tag["weights_comfort"])

    def test_설문_완료_시_survey_completed가_True다(
        self, service, auth_service, mock_user, mock_preference
    ):
        kwargs = _get_upsert_kwargs(service, auth_service, mock_user, mock_preference, tags=[])
        assert kwargs["survey_completed"] is True

    def test_선택한_태그는_참고용으로_selected_tags에_그대로_저장된다(
        self, service, auth_service, mock_user, mock_preference
    ):
        kwargs = _get_upsert_kwargs(
            service, auth_service, mock_user, mock_preference, tags=["안전", "편안"],
        )
        assert kwargs["selected_tags"] == ["안전", "편안"]


# ── 거리 매핑 ────────────────────────────────────────────────────────────────


class TestDistanceMapping:
    def test_slow는_2_0km다(self, service, auth_service, mock_user, mock_preference):
        kwargs = _get_upsert_kwargs(
            service, auth_service, mock_user, mock_preference,
            tags=[], distance=DistanceOption.SLOW,
        )
        assert kwargs["default_target_km"] == 2.0

    def test_normal은_3_0km다(self, service, auth_service, mock_user, mock_preference):
        kwargs = _get_upsert_kwargs(
            service, auth_service, mock_user, mock_preference,
            tags=[], distance=DistanceOption.NORMAL,
        )
        assert kwargs["default_target_km"] == 3.0

    def test_fast는_5_0km다(self, service, auth_service, mock_user, mock_preference):
        kwargs = _get_upsert_kwargs(
            service, auth_service, mock_user, mock_preference,
            tags=[], distance=DistanceOption.FAST,
        )
        assert kwargs["default_target_km"] == 5.0

    def test_distance_없으면_None이다(self, service, auth_service, mock_user, mock_preference):
        kwargs = _get_upsert_kwargs(service, auth_service, mock_user, mock_preference, tags=[])
        assert kwargs["default_target_km"] is None
