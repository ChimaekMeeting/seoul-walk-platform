"""
tests/unit/test_survey_service.py
SurveyService 단위 테스트

검증 항목:
  - 인증 실패 시 status 반환
  - 사용자 미존재 시 USER_NOT_FOUND 반환
  - 태그 없을 때 모든 가중치 기본값 0.5
  - 단일 태그 가중치 적용
  - 동일 가중치 여러 태그 누적
  - 가중치 최대값 1.0 클램핑
  - 음수 델타 적용 (slope -)
  - 가중치 최소값 0.0 클램핑
  - 알 수 없는 태그 무시
  - 이중 dimension 태그
  - slope 양수/음수 태그 혼합
  - 거리 선택지 → default_target_km 매핑
"""

import pytest
from unittest.mock import MagicMock, patch

from src.service.user.survey_service import SurveyService
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
    pref.weights_nature = None
    pref.weights_slope = None
    pref.weights_running = None
    pref.weights_landmark = None
    pref.weights_child = None
    return pref


def _get_upsert_kwargs(service, auth_service, mock_user, mock_preference, tags, distance=None):
    """설문 제출 후 upsert에 전달된 kwargs를 반환하는 헬퍼."""
    auth_service.check_access_token.return_value = (Status.SUCCESS, Provider.KAKAO, "kakao-123")
    with patch(
        "src.service.user.survey_service.UserRepository.find_by_provider_and_provider_id",
        return_value=mock_user,
    ):
        with patch(
            "src.service.user.survey_service.UserPreferenceRepository.upsert",
            return_value=mock_preference,
        ) as mock_upsert:
            service.submit("valid_token", SurveyRequest(tags=tags, distance=distance))
            return mock_upsert.call_args.kwargs


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


# ── 가중치 계산 ──────────────────────────────────────────────────────────────


class TestCalculateWeights:
    def test_태그_없으면_모든_가중치가_0_5다(
        self, service, auth_service, mock_user, mock_preference
    ):
        kwargs = _get_upsert_kwargs(service, auth_service, mock_user, mock_preference, tags=[])
        assert kwargs["weights_safety"]   == pytest.approx(0.5)
        assert kwargs["weights_nature"]   == pytest.approx(0.5)
        assert kwargs["weights_slope"]    == pytest.approx(0.5)
        assert kwargs["weights_running"]  == pytest.approx(0.5)
        assert kwargs["weights_landmark"] == pytest.approx(0.5)
        assert kwargs["weights_child"]    == pytest.approx(0.5)

    def test_단일_태그가_가중치에_적용된다(
        self, service, auth_service, mock_user, mock_preference
    ):
        # "나무 많은" → nature +0.2 → 0.7
        kwargs = _get_upsert_kwargs(
            service, auth_service, mock_user, mock_preference, tags=["나무 많은"]
        )
        assert kwargs["weights_nature"] == pytest.approx(0.7)
        assert kwargs["weights_safety"] == pytest.approx(0.5)  # 나머지 불변

    def test_같은_가중치_여러_태그가_누적된다(
        self, service, auth_service, mock_user, mock_preference
    ):
        # "나무 많은"(+0.2) + "꽃길"(+0.2) → nature 0.9
        kwargs = _get_upsert_kwargs(
            service, auth_service, mock_user, mock_preference, tags=["나무 많은", "꽃길"]
        )
        assert kwargs["weights_nature"] == pytest.approx(0.9)

    def test_가중치_최대값이_1_0으로_클램핑된다(
        self, service, auth_service, mock_user, mock_preference
    ):
        # nature 태그 4개 → 0.5 + 0.8 = 1.3 → 클램핑 → 1.0
        kwargs = _get_upsert_kwargs(
            service, auth_service, mock_user, mock_preference,
            tags=["나무 많은", "꽃길", "햇살 좋은", "나무 많은"],
        )
        assert kwargs["weights_nature"] == pytest.approx(1.0)

    def test_음수_델타가_적용된다(
        self, service, auth_service, mock_user, mock_preference
    ):
        # "뛰고 싶은" → running +0.2 → 0.7, slope -0.1 → 0.4
        kwargs = _get_upsert_kwargs(
            service, auth_service, mock_user, mock_preference, tags=["뛰고 싶은"]
        )
        assert kwargs["weights_running"] == pytest.approx(0.7)  # 0.6 → 0.7
        assert kwargs["weights_slope"]   == pytest.approx(0.4)

    def test_가중치_최소값이_0_0으로_클램핑된다(
        self, service, auth_service, mock_user, mock_preference
    ):
        # slope 음수 태그 10개 → 0.0 미만 방지
        kwargs = _get_upsert_kwargs(
            service, auth_service, mock_user, mock_preference,
            tags=["뛰고 싶은"] * 10,
        )
        assert kwargs["weights_slope"] >= 0.0

    def test_알_수_없는_태그는_무시된다(
        self, service, auth_service, mock_user, mock_preference
    ):
        kwargs = _get_upsert_kwargs(
            service, auth_service, mock_user, mock_preference, tags=["존재하지않는태그"]
        )
        assert kwargs["weights_nature"] == pytest.approx(0.5)

    def test_이중_dimension_태그가_두_가중치에_반영된다(
        self, service, auth_service, mock_user, mock_preference
    ):
        # "반려동물" → nature +0.1 → 0.6, child +0.1 → 0.6
        kwargs = _get_upsert_kwargs(
            service, auth_service, mock_user, mock_preference, tags=["반려동물"]  # "반려동물과" → "반려동물"
        )
        assert kwargs["weights_nature"] == pytest.approx(0.6)
        assert kwargs["weights_child"]  == pytest.approx(0.6)


    def test_slope_양수_음수_태그가_함께_적용된다(
        self, service, auth_service, mock_user, mock_preference
    ):
        # "숨 안 차는"(+0.3) + "뛰고 싶은"(-0.1) → 0.5 + 0.3 - 0.1 = 0.7
        kwargs = _get_upsert_kwargs(
            service, auth_service, mock_user, mock_preference,
            tags=["숨 안 차는", "뛰고 싶은"],
        )
        assert kwargs["weights_slope"] == pytest.approx(0.7)

    def test_설문_완료_시_survey_completed가_True다(
        self, service, auth_service, mock_user, mock_preference
    ):
        kwargs = _get_upsert_kwargs(service, auth_service, mock_user, mock_preference, tags=[])
        assert kwargs["survey_completed"] is True


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
