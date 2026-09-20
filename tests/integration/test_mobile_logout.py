"""실제 JWT·라우터·서비스와 메모리 캐시로 검증하는 모바일 로그아웃 계약.

DB/Graph 시작과 외부 API는 호출하지 않는다. 실제 Valkey 연결·TTL 검증은 별도다.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient

from src.entity.user import Provider
from src.interfaces.dependencies import get_auth_service, get_kakao_login_service
from src.main import app
from src.service.user.auth_service import AuthService
from src.service.user.login_service import KakaoLoginService


_URL = "/api/login/kakao/logout"
_KEY = f"refresh_token:{Provider.KAKAO.value}:42"
_OTHER_KEY = f"refresh_token:{Provider.KAKAO.value}:99"
_ACCESS_SECRET = "logout-test-access-secret-at-least-32-bytes"
_REFRESH_SECRET = "logout-test-refresh-secret-at-least-32-bytes"


def _token(kind, provider_id="42", *, expired=False, secret=None):
    return jwt.encode(
        {
            "provider": Provider.KAKAO.value,
            "provider_id": provider_id,
            "type": kind,
            "exp": datetime.now(timezone.utc)
            + (timedelta(seconds=-60) if expired else timedelta(hours=1)),
        },
        secret or (_ACCESS_SECRET if kind == "access" else _REFRESH_SECRET),
        algorithm="HS256",
    )


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setenv("ACCESS_SECRET_KEY", _ACCESS_SECRET)
    monkeypatch.setenv("REFRESH_SECRET_KEY", _REFRESH_SECRET)
    auth = AuthService()
    users = MagicMock()
    login = KakaoLoginService(users, auth)
    refresh = _token("refresh")
    other_refresh = _token("refresh", "99")
    saved = {_KEY: refresh, _OTHER_KEY: other_refresh}
    cache = SimpleNamespace(
        get=AsyncMock(side_effect=lambda key: saved.get(key)),
        delete=AsyncMock(side_effect=lambda key: saved.pop(key, None)),
    )
    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_kakao_login_service] = lambda: login
    app.dependency_overrides[get_auth_service] = lambda: auth
    try:
        with (
            patch("src.main.init_db"),
            patch("src.main.init_route_service"),
            patch(
                "src.infrastructure.cache.repository.user_repository.get_valkey_db",
                return_value=cache,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            yield SimpleNamespace(
                client=client, saved=saved, cache=cache, users=users,
                refresh=refresh, other_refresh=other_refresh,
            )
        assert not users.mock_calls
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


def _assert_success(response):
    assert response.status_code == 200
    assert response.json() == {"status": "success", "access_token": None}
    cookies = response.headers.get_list("set-cookie")
    for name in ("access_token", "refresh_token"):
        assert any(f'{name}=""' in item and "Max-Age=0" in item for item in cookies)


@pytest.mark.parametrize("access", [None, "expired", "valid"])
def test_mobile_logout_revokes_refresh_and_preserves_other_user(session, access):
    headers = {}
    if access:
        headers["Authorization"] = f"Bearer {_token('access', expired=access == 'expired')}"
    response = session.client.post(
        _URL, headers=headers, json={"refresh_token": session.refresh},
    )
    _assert_success(response)
    assert _KEY not in session.saved
    assert session.saved[_OTHER_KEY] == session.other_refresh
    session.cache.delete.assert_awaited_once_with(_KEY)

    # 로그아웃 뒤 같은 refresh로 access를 다시 발급할 수 없어야 한다.
    renewed = session.client.get(
        "/api/auth/check/refresh_token",
        headers={"Authorization": f"Bearer {session.refresh}"},
    )
    assert renewed.status_code == 200
    assert renewed.json() == {"status": "invalid_token", "access_token": None}


@pytest.mark.parametrize("source", ["access_header", "access_cookie", "refresh_cookie", "expired_access_cookie"])
def test_legacy_bodyless_logout_still_works(session, source):
    headers = {}
    if source == "access_header":
        headers["Authorization"] = f"Bearer {_token('access')}"
    elif source == "access_cookie":
        session.client.cookies.set("access_token", _token("access"))
    else:
        session.client.cookies.set("refresh_token", session.refresh)
        if source == "expired_access_cookie":
            session.client.cookies.set("access_token", _token("access", expired=True))
    _assert_success(session.client.post(_URL, headers=headers))
    assert _KEY not in session.saved
    assert _OTHER_KEY in session.saved


def test_logout_is_idempotent(session):
    for _ in range(2):
        _assert_success(session.client.post(_URL, json={"refresh_token": session.refresh}))
    session.cache.delete.assert_awaited_once_with(_KEY)


def test_no_tokens_only_clears_cookies(session):
    _assert_success(session.client.post(_URL))
    session.cache.delete.assert_not_awaited()
    assert len(session.saved) == 2


@pytest.mark.parametrize("kind", ["expired", "bad_signature", "malformed", "stale", "access_in_body"])
def test_invalid_refresh_cannot_revoke_or_fall_back_to_cookie(session, kind):
    tokens = {
        "expired": _token("refresh", expired=True),
        "bad_signature": _token("refresh", secret="another-secret-at-least-32-bytes-long"),
        "malformed": "invalid-refresh-token",
        "stale": _token("refresh"),
        "access_in_body": _token("access"),
    }
    if kind == "stale":
        session.saved[_KEY] = "newer-login-refresh-token"
    session.client.cookies.set("refresh_token", session.other_refresh)
    response = session.client.post(
        _URL,
        headers={"Authorization": f"Bearer {_token('access', expired=True)}"},
        json={"refresh_token": tokens[kind]},
    )
    _assert_success(response)
    session.cache.delete.assert_not_awaited()
    assert len(session.saved) == 2


def test_body_refresh_has_priority_over_cookie(session):
    session.client.cookies.set("refresh_token", session.other_refresh)
    _assert_success(session.client.post(_URL, json={"refresh_token": session.refresh}))
    assert _KEY not in session.saved
    assert _OTHER_KEY in session.saved


def test_valid_access_keeps_existing_priority_over_refresh(session):
    _assert_success(session.client.post(
        _URL, headers={"Authorization": f"Bearer {_token('access')}"},
        json={"refresh_token": session.other_refresh},
    ))
    assert _KEY not in session.saved
    assert _OTHER_KEY in session.saved


def test_expired_bearer_does_not_use_other_users_access_cookie(session):
    session.client.cookies.set("access_token", _token("access", "99"))
    _assert_success(session.client.post(
        _URL, headers={"Authorization": f"Bearer {_token('access', expired=True)}"},
        json={"refresh_token": session.refresh},
    ))
    assert _KEY not in session.saved
    assert _OTHER_KEY in session.saved


@pytest.mark.parametrize("header", ["Basic abc", "Bearer", "Bearer a b"])
def test_malformed_authorization_still_returns_401(session, header):
    response = session.client.post(
        _URL, headers={"Authorization": header},
        json={"refresh_token": session.refresh},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid_token"}
    session.cache.delete.assert_not_awaited()


@pytest.mark.parametrize("body", [{}, {"refresh_token": None}, {"refresh_token": ""}, {"refresh_token": "   "}, {"refresh_token": 123}])
def test_invalid_body_returns_safe_422_without_revoking(session, body):
    response = session.client.post(_URL, json=body)
    assert response.status_code == 422
    assert all(set(item) == {"type", "loc", "msg"} for item in response.json()["detail"])
    session.cache.delete.assert_not_awaited()


@pytest.mark.parametrize("operation", ["get", "delete"])
def test_cache_failure_is_not_reported_as_success(session, operation):
    getattr(session.cache, operation).side_effect = RuntimeError("private-cache-detail")
    response = session.client.post(_URL, json={"refresh_token": session.refresh})
    assert response.status_code == 500
    assert response.json() == {"detail": "서버 내부 오류가 발생했습니다."}
    assert "private-cache-detail" not in response.text
    assert _KEY in session.saved


def test_logout_does_not_immediately_revoke_stateless_access_token(session):
    access = _token("access")
    _assert_success(session.client.post(_URL, json={"refresh_token": session.refresh}))
    checked = session.client.get(
        "/api/auth/check/access_token", headers={"Authorization": f"Bearer {access}"},
    )
    assert checked.json()["status"] == "success"


def test_openapi_exposes_optional_logout_body_and_required_refresh_field(session):
    schema = session.client.get("/openapi.json").json()
    operation = schema["paths"][_URL]["post"]
    assert not operation["requestBody"].get("required", False)
    model = schema["components"]["schemas"]["LogoutRequest"]
    assert model["required"] == ["refresh_token"]
    assert model["properties"]["refresh_token"]["minLength"] == 1
    assert {"401", "422", "500"} <= operation["responses"].keys()
