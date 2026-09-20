"""현행 Provider 기반 JWT 발급·검증 계약의 단위 테스트."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from jwt.exceptions import InvalidTokenError

from src.entity.user import Provider
from src.interfaces.schema.auth_schema import Status
from src.service.user.auth_service import AuthService


_ACCESS_SECRET = "test-access-secret-key-at-least-32-bytes"
_REFRESH_SECRET = "test-refresh-secret-key-at-least-32-bytes"
_PROVIDER = Provider.KAKAO
_PROVIDER_ID = "42"


@pytest.fixture
def service():
    with patch.dict(
        "os.environ",
        {
            "ACCESS_SECRET_KEY": _ACCESS_SECRET,
            "REFRESH_SECRET_KEY": _REFRESH_SECRET,
        },
    ):
        yield AuthService()


def _access_token(service: AuthService) -> str:
    return service.get_access_token(_PROVIDER, _PROVIDER_ID)


def _refresh_token(service: AuthService) -> str:
    return service.get_refresh_token(_PROVIDER, _PROVIDER_ID)


class TestGetAccessToken:
    def test_현행_payload와_만료시간을_사용한다(self, service):
        before = datetime.now(timezone.utc)
        token = _access_token(service)
        payload = jwt.decode(token, _ACCESS_SECRET, algorithms=["HS256"])

        assert isinstance(token, str)
        assert payload["provider"] == _PROVIDER.value
        assert payload["provider_id"] == _PROVIDER_ID
        assert payload["type"] == "access"
        expiry = datetime.fromtimestamp(payload["exp"], tz=timezone.utc) - before
        assert timedelta(minutes=59, seconds=55) <= expiry <= timedelta(
            minutes=60, seconds=5
        )


class TestGetRefreshToken:
    def test_현행_payload와_만료시간을_사용한다(self, service):
        before = datetime.now(timezone.utc)
        token = _refresh_token(service)
        payload = jwt.decode(token, _REFRESH_SECRET, algorithms=["HS256"])

        assert isinstance(token, str)
        assert payload["provider"] == _PROVIDER.value
        assert payload["provider_id"] == _PROVIDER_ID
        assert payload["type"] == "refresh"
        expiry = datetime.fromtimestamp(payload["exp"], tz=timezone.utc) - before
        assert timedelta(days=13, hours=23) <= expiry <= timedelta(days=14, seconds=5)


class TestDecode:
    def test_access와_refresh가_provider_tuple로_복원된다(self, service):
        assert service.decode(access_token=_access_token(service)) == (
            _PROVIDER,
            _PROVIDER_ID,
        )
        assert service.decode(refresh_token=_refresh_token(service)) == (
            _PROVIDER,
            _PROVIDER_ID,
        )

    def test_두_인수_모두_None이면_ValueError를_발생시킨다(self, service):
        with pytest.raises(ValueError):
            service.decode()

    def test_잘못된_서명과_만료를_구분한다(self, service):
        invalid = jwt.encode(
            {"provider": _PROVIDER.value, "provider_id": _PROVIDER_ID},
            "wrong-secret-key-at-least-32-bytes",
            algorithm="HS256",
        )
        with pytest.raises(InvalidTokenError):
            service.decode(access_token=invalid)

        expired = jwt.encode(
            {
                "provider": _PROVIDER.value,
                "provider_id": _PROVIDER_ID,
                "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
                "type": "access",
            },
            _ACCESS_SECRET,
            algorithm="HS256",
        )
        with pytest.raises(ValueError):
            service.decode(access_token=expired)

    def test_refresh_token이_있으면_access_token보다_우선한다(self, service):
        result = service.decode(
            refresh_token=_refresh_token(service),
            access_token=_access_token(service),
        )
        assert result == (_PROVIDER, _PROVIDER_ID)


class TestCheckAccessToken:
    def test_성공_실패_반환값은_항상_세_개다(self, service):
        assert service.check_access_token(_access_token(service)) == (
            Status.SUCCESS,
            _PROVIDER,
            _PROVIDER_ID,
        )

        invalid = jwt.encode(
            {"provider": _PROVIDER.value, "provider_id": _PROVIDER_ID},
            "wrong-secret-key-at-least-32-bytes",
            algorithm="HS256",
        )
        assert service.check_access_token(invalid) == (
            Status.INVALID_TOKEN,
            None,
            None,
        )
        assert service.check_access_token(None) == (
            Status.ACCESS_EXPIRED_TOKEN,
            None,
            None,
        )

    def test_만료된_토큰을_ACCESS_EXPIRED_TOKEN으로_반환한다(self, service):
        expired = jwt.encode(
            {
                "provider": _PROVIDER.value,
                "provider_id": _PROVIDER_ID,
                "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
                "type": "access",
            },
            _ACCESS_SECRET,
            algorithm="HS256",
        )
        assert service.check_access_token(expired) == (
            Status.ACCESS_EXPIRED_TOKEN,
            None,
            None,
        )

    def test_refresh_token은_access_token으로_사용할_수_없다(self, service):
        assert service.check_access_token(_refresh_token(service)) == (
            Status.INVALID_TOKEN,
            None,
            None,
        )


class TestCheckRefreshToken:
    def test_저장값이_일치하면_새_access_token을_반환한다(self, service):
        refresh_token = _refresh_token(service)
        cache_get = AsyncMock(return_value=refresh_token)
        with patch(
            "src.service.user.auth_service.CacheUserRepository.get_refresh_token",
            new=cache_get,
        ):
            status, new_access, provider_id = asyncio.run(
                service.check_refresh_token(refresh_token)
            )

        assert status == Status.SUCCESS
        assert provider_id == _PROVIDER_ID
        assert service.decode(access_token=new_access) == (_PROVIDER, _PROVIDER_ID)
        cache_get.assert_awaited_once_with(_PROVIDER, _PROVIDER_ID)

    def test_저장값_불일치는_INVALID_TOKEN이다(self, service):
        with patch(
            "src.service.user.auth_service.CacheUserRepository.get_refresh_token",
            new=AsyncMock(return_value="different-token"),
        ):
            result = asyncio.run(service.check_refresh_token(_refresh_token(service)))
        assert result == (Status.INVALID_TOKEN, None, None)

    def test_잘못된_서명_만료_누락을_구분한다(self, service):
        invalid = jwt.encode(
            {"provider": _PROVIDER.value, "provider_id": _PROVIDER_ID},
            "wrong-secret-key-at-least-32-bytes",
            algorithm="HS256",
        )
        assert asyncio.run(service.check_refresh_token(invalid)) == (
            Status.INVALID_TOKEN,
            None,
            None,
        )

        expired = jwt.encode(
            {
                "provider": _PROVIDER.value,
                "provider_id": _PROVIDER_ID,
                "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
                "type": "refresh",
            },
            _REFRESH_SECRET,
            algorithm="HS256",
        )
        assert asyncio.run(service.check_refresh_token(expired)) == (
            Status.REFRESH_EXPIRED_TOKEN,
            None,
            None,
        )
        assert asyncio.run(service.check_refresh_token(None)) == (
            Status.REFRESH_EXPIRED_TOKEN,
            None,
            None,
        )

    def test_access_token은_refresh_token으로_사용할_수_없다(self, service):
        assert asyncio.run(service.check_refresh_token(_access_token(service))) == (
            Status.INVALID_TOKEN,
            None,
            None,
        )
