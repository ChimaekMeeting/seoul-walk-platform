"""
tests/unit/test_auth_service.py
AuthService 단위 테스트

담당: QA (예원)
검증 항목:
  - JWT access/refresh 토큰 발급
  - 토큰 디코딩 및 provider_id 추출
  - 만료 토큰 처리
  - 잘못된 서명 처리
  - check_access_token / check_refresh_token 상태 반환
"""

import pytest
import jwt
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from jwt.exceptions import InvalidTokenError

from src.service.user.auth_service import AuthService
from src.interfaces.schema.auth_schema import Status

# ── 공통 픽스처 ──────────────────────────────────────────────────────────────


@pytest.fixture
def service():
    """환경변수 없이 테스트용 시크릿 키를 주입한 AuthService."""
    with patch.dict(
        "os.environ",
        {
            "ACCESS_SECRET_KEY": "test-access-secret",
            "REFRESH_SECRET_KEY": "test-refresh-secret",
        },
    ):
        yield AuthService()


PROVIDER_ID = 42


# ── 토큰 발급 ────────────────────────────────────────────────────────────────


class TestGetAccessToken:
    def test_반환값이_문자열이다(self, service):
        token = service.get_access_token(PROVIDER_ID)
        assert isinstance(token, str)

    def test_payload에_provider_id가_sub으로_들어간다(self, service):
        token = service.get_access_token(PROVIDER_ID)
        payload = jwt.decode(token, "test-access-secret", algorithms=["HS256"])
        assert payload["sub"] == str(PROVIDER_ID)

    def test_payload_type이_access다(self, service):
        token = service.get_access_token(PROVIDER_ID)
        payload = jwt.decode(token, "test-access-secret", algorithms=["HS256"])
        assert payload["type"] == "access"

    def test_만료시간이_60분이다(self, service):
        before = datetime.now(timezone.utc)
        token = service.get_access_token(PROVIDER_ID)
        payload = jwt.decode(token, "test-access-secret", algorithms=["HS256"])
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        delta = exp - before
        # 60분 ±5초 허용
        assert (
            timedelta(minutes=59, seconds=55)
            <= delta
            <= timedelta(minutes=60, seconds=5)
        )


class TestGetRefreshToken:
    def test_반환값이_문자열이다(self, service):
        token = service.get_refresh_token(PROVIDER_ID)
        assert isinstance(token, str)

    def test_payload에_provider_id가_sub으로_들어간다(self, service):
        token = service.get_refresh_token(PROVIDER_ID)
        payload = jwt.decode(token, "test-refresh-secret", algorithms=["HS256"])
        assert payload["sub"] == str(PROVIDER_ID)

    def test_payload_type이_refresh다(self, service):
        token = service.get_refresh_token(PROVIDER_ID)
        payload = jwt.decode(token, "test-refresh-secret", algorithms=["HS256"])
        assert payload["type"] == "refresh"

    def test_만료시간이_14일이다(self, service):
        before = datetime.now(timezone.utc)
        token = service.get_refresh_token(PROVIDER_ID)
        payload = jwt.decode(token, "test-refresh-secret", algorithms=["HS256"])
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        delta = exp - before
        assert timedelta(days=13, hours=23) <= delta <= timedelta(days=14, seconds=5)


# ── decode ───────────────────────────────────────────────────────────────────


class TestDecode:
    def test_유효한_access_token에서_provider_id를_반환한다(self, service):
        token = service.get_access_token(PROVIDER_ID)
        result = service.decode(access_token=token)
        assert result == PROVIDER_ID

    def test_유효한_refresh_token에서_provider_id를_반환한다(self, service):
        token = service.get_refresh_token(PROVIDER_ID)
        result = service.decode(refresh_token=token)
        assert result == PROVIDER_ID

    def test_두_인수_모두_None이면_ValueError를_발생시킨다(self, service):
        with pytest.raises(ValueError):
            service.decode()

    def test_잘못된_서명의_access_token은_InvalidTokenError를_발생시킨다(self, service):
        fake_token = jwt.encode({"sub": "42"}, "wrong-secret", algorithm="HS256")
        with pytest.raises(InvalidTokenError):
            service.decode(access_token=fake_token)

    def test_만료된_access_token은_ValueError를_발생시킨다(self, service):
        expired_payload = {
            "sub": str(PROVIDER_ID),
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
            "type": "access",
        }
        expired_token = jwt.encode(
            expired_payload, "test-access-secret", algorithm="HS256"
        )
        with pytest.raises(ValueError):
            service.decode(access_token=expired_token)

    def test_refresh_token이_있으면_access_token보다_우선한다(self, service):
        """두 토큰 모두 전달 시 refresh_token을 먼저 처리해야 한다."""
        refresh = service.get_refresh_token(PROVIDER_ID)
        access = service.get_access_token(PROVIDER_ID)
        result = service.decode(refresh_token=refresh, access_token=access)
        assert result == PROVIDER_ID


# ── check_access_token ───────────────────────────────────────────────────────


class TestCheckAccessToken:
    def test_유효한_토큰이면_SUCCESS와_provider_id를_반환한다(self, service):
        token = service.get_access_token(PROVIDER_ID)
        status, pid = service.check_access_token(access_token=token)
        assert status == Status.SUCCESS
        assert pid == PROVIDER_ID

    def test_잘못된_서명이면_INVALID_TOKEN과_None을_반환한다(self, service):
        fake = jwt.encode({"sub": "42"}, "wrong-secret", algorithm="HS256")
        status, pid = service.check_access_token(access_token=fake)
        assert status == Status.INVALID_TOKEN
        assert pid is None

    def test_만료된_토큰이면_ACCESS_EXPIRED_TOKEN과_None을_반환한다(self, service):
        expired_payload = {
            "sub": str(PROVIDER_ID),
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
            "type": "access",
        }
        expired_token = jwt.encode(
            expired_payload, "test-access-secret", algorithm="HS256"
        )
        status, pid = service.check_access_token(access_token=expired_token)
        assert status == Status.ACCESS_EXPIRED_TOKEN
        assert pid is None


# ── check_refresh_token ──────────────────────────────────────────────────────


class TestCheckRefreshToken:
    def test_유효한_토큰이면_SUCCESS와_새_access_token과_provider_id를_반환한다(
        self, service
    ):
        token = service.get_refresh_token(PROVIDER_ID)
        status, new_access, pid = service.check_refresh_token(refresh_token=token)
        assert status == Status.SUCCESS
        assert isinstance(new_access, str)
        assert pid == PROVIDER_ID

    def test_새_access_token이_디코딩_가능하다(self, service):
        token = service.get_refresh_token(PROVIDER_ID)
        _, new_access, _ = service.check_refresh_token(refresh_token=token)
        payload = jwt.decode(new_access, "test-access-secret", algorithms=["HS256"])
        assert payload["sub"] == str(PROVIDER_ID)

    def test_잘못된_서명이면_INVALID_TOKEN을_반환한다(self, service):
        fake = jwt.encode({"sub": "42"}, "wrong-secret", algorithm="HS256")
        status, new_access, pid = service.check_refresh_token(refresh_token=fake)
        assert status == Status.INVALID_TOKEN
        assert new_access is None
        assert pid is None

    def test_만료된_토큰이면_REFRESH_EXPIRED_TOKEN을_반환한다(self, service):
        expired_payload = {
            "sub": str(PROVIDER_ID),
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
            "type": "refresh",
        }
        expired_token = jwt.encode(
            expired_payload, "test-refresh-secret", algorithm="HS256"
        )
        status, new_access, pid = service.check_refresh_token(
            refresh_token=expired_token
        )
        assert status == Status.REFRESH_EXPIRED_TOKEN
        assert new_access is None
        assert pid is None
