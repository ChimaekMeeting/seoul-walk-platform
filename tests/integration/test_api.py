"""
tests/integration/test_api.py
API 엔드포인트 통합 테스트

담당: QA (예원)
검증 항목:
  - POST /api/walk/route
  - GET  /api/auth/check/access_token
  - GET  /api/auth/check/refresh_token
  - POST /api/prewalk/init
  - POST /api/prewalk/intent
  - GET  /api/map/facilities
  - GET  /api/map/points
  - GET  /api/map/edges

실행 방법:
  pytest tests/integration/ -v
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient

from src.main import app
from src.interfaces.schema.walk_schema import (
    WalkRouteResponse,
    WalkRouteStatus,
    WalkMode,
)
from src.interfaces.schema.auth_schema import Status
from src.interfaces.schema.survey_schema import SurveyResponse, SurveyStatus
from src.service.user.auth_service import AuthService
from src.entity.user import Provider

# ── 공통 픽스처 ──────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    with patch("src.main.init_db"), patch("src.main.init_route_service"):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


@pytest.fixture
def auth_service():
    with patch.dict(
        "os.environ",
        {
            "ACCESS_SECRET_KEY": "test-access-secret-key-long-enough",
            "REFRESH_SECRET_KEY": "test-refresh-secret-key-long-enough",
        },
    ):
        yield AuthService()


# ── POST /api/walk/route ─────────────────────────────────────────────────────


class TestWalkRouteAPI:
    def test_순환_랜덤_경로_요청_성공(self, client):
        mock_service = MagicMock()
        mock_service.get_route.return_value = [WalkRouteResponse(
            status=WalkRouteStatus.SUCCESS,
            mode=WalkMode.CIRCULAR_RANDOM,
            coordinates=[[37.5, 127.0], [37.51, 127.01], [37.5, 127.0]],
            total_km=3.1,
        )]
        with patch("src.interfaces.dependencies.route_service", mock_service):
            response = client.post(
                "/api/walk/route",
                json={
                    "origin": {"lat": 37.5, "lon": 127.0},
                    "mode": "circular_random",
                    "target_km": 3.0,
                },
            )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["mode"] == "circular_random"
        assert len(body["coordinates"]) > 0
        assert body["total_km"] == 3.1

    def test_편도_최단_경로_요청_성공(self, client):
        mock_service = MagicMock()
        mock_service.get_route.return_value = [WalkRouteResponse(
            status=WalkRouteStatus.SUCCESS,
            mode=WalkMode.ONEWAY_SHORTEST,
            coordinates=[[37.5, 127.0], [37.55, 127.05], [37.6, 127.1]],
            total_km=7.2,
        )]
        with patch("src.interfaces.dependencies.route_service", mock_service):
            response = client.post(
                "/api/walk/route",
                json={
                    "origin": {"lat": 37.5, "lon": 127.0},
                    "destination": {"lat": 37.51, "lon": 127.01},
                    "mode": "oneway_shortest",
                    "target_km": 3.0,
                },
            )
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    def test_경로_생성_실패_시_상태값을_반환한다(self, client):
        mock_service = MagicMock()
        mock_service.get_route.return_value = [WalkRouteResponse(
            status=WalkRouteStatus.NO_NEAREST_START_NODE,
            mode=WalkMode.CIRCULAR_RANDOM,
            coordinates=[],
            total_km=0.0,
        )]
        with patch("src.interfaces.dependencies.route_service", mock_service):
            response = client.post(
                "/api/walk/route",
                json={
                    "origin": {"lat": 37.5, "lon": 127.0},
                    "mode": "circular_random",
                },
            )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "no_nearest_start_node"

    def test_경로_생성_실패_시_no_path_상태값을_반환한다(self, client):
        mock_service = MagicMock()
        mock_service.get_route.return_value = [WalkRouteResponse(
            status=WalkRouteStatus.NO_PATH,
            mode=WalkMode.CIRCULAR_RANDOM,
            coordinates=[],
            total_km=0.0,
        )]
        with patch("src.interfaces.dependencies.route_service", mock_service):
            response = client.post(
                "/api/walk/route",
                json={
                    "origin": {"lat": 37.5, "lon": 127.0},
                    "mode": "circular_random",
                },
            )
        assert response.status_code == 200
        assert response.json()["status"] == "no_path"

    def test_편도_경로_요청_destination_없으면_invalid_destination_상태값을_반환한다(self, client):
        mock_service = MagicMock()
        mock_service.get_route.return_value = [WalkRouteResponse(
            status=WalkRouteStatus.INVALID_DESTINATION,
            mode=WalkMode.ONEWAY_SHORTEST,
            coordinates=[],
            total_km=0.0,
        )]
        with patch("src.interfaces.dependencies.route_service", mock_service):
            response = client.post(
                "/api/walk/route",
                json={
                    "origin": {"lat": 37.5, "lon": 127.0},
                    "destination": {"lat": 37.51, "lon": 127.01},
                    "mode": "oneway_shortest",
                    "target_km": 3.0,
                },
            )
        assert response.status_code == 200
        assert response.json()["status"] == "invalid_destination"

    def test_알수없는_오류는_unknown_error_상태값을_반환한다(self, client):
        mock_service = MagicMock()
        mock_service.get_route.return_value = [WalkRouteResponse(
            status=WalkRouteStatus.UNKNOWN_ERROR,
            mode=WalkMode.CIRCULAR_RANDOM,
            coordinates=[],
            total_km=0.0,
        )]
        with patch("src.interfaces.dependencies.route_service", mock_service):
            response = client.post(
                "/api/walk/route",
                json={
                    "origin": {"lat": 37.5, "lon": 127.0},
                    "mode": "circular_random",
                },
            )
        assert response.status_code == 200
        assert response.json()["status"] == "unknown_error"

    def test_필수_필드_누락_시_422_반환(self, client):
        response = client.post("/api/walk/route", json={"mode": "circular_random"})
        assert response.status_code == 422

    def test_서비스_내부_오류_시_500_반환(self, client):
        mock_service = MagicMock()
        mock_service.get_route.side_effect = RuntimeError("그래프 로드 실패")
        with patch("src.interfaces.dependencies.route_service", mock_service):
            response = client.post(
                "/api/walk/route",
                json={
                    "origin": {"lat": 37.5, "lon": 127.0},
                    "mode": "circular_random",
                },
            )
        assert response.status_code == 500
        assert response.json() == {"detail": "서버 내부 오류가 발생했습니다."}
        assert "그래프 로드 실패" not in response.text

    @pytest.mark.parametrize(
        "target_km",
        ["0", "-1", "11", "NaN", "Infinity", "-Infinity", True, False],
    )
    def test_잘못된_목표_거리는_서비스_호출_전_422로_거절한다(self, client, target_km):
        mock_service = MagicMock()
        with patch("src.interfaces.dependencies.route_service", mock_service):
            response = client.post(
                "/api/walk/route",
                json={
                    "origin": {"lat": 37.5, "lon": 127.0},
                    "mode": "circular_random",
                    "target_km": target_km,
                },
            )

        assert response.status_code == 422
        mock_service.get_route.assert_not_called()

    @pytest.mark.parametrize(
        "raw_target_km",
        [
            str(10**400),
            str(-(10**400)),
            "1e400",
            "-1e400",
            "NaN",
            "Infinity",
            "-Infinity",
        ],
    )
    def test_실제_JSON_극단값은_안전한_422로_반환한다(self, client, raw_target_km):
        mock_service = MagicMock()
        raw_body = (
            '{"origin":{"lat":37.5,"lon":127.0},'
            '"mode":"circular_random",'
            f'"target_km":{raw_target_km}'
            '}'
        )
        with patch("src.interfaces.dependencies.route_service", mock_service):
            response = client.post(
                "/api/walk/route",
                content=raw_body,
                headers={"content-type": "application/json"},
            )

        assert response.status_code == 422
        body = response.json()
        assert isinstance(body["detail"], list)
        assert all(set(error) <= {"type", "loc", "msg"} for error in body["detail"])
        assert raw_target_km not in response.text
        mock_service.get_route.assert_not_called()

    @pytest.mark.parametrize(
        ("headers", "expected_token"),
        [
            ({"Authorization": "Bearer bearer-token"}, "bearer-token"),
            ({"Cookie": "access_token=cookie-token"}, "cookie-token"),
            (
                {
                    "Authorization": "Bearer bearer-token",
                    "Cookie": "access_token=cookie-token",
                },
                "bearer-token",
            ),
        ],
    )
    def test_Bearer_우선_쿠키_fallback으로_access_token을_전달한다(
        self, client, headers, expected_token
    ):
        mock_service = MagicMock()
        mock_service.get_route.return_value = [WalkRouteResponse(
            status=WalkRouteStatus.SUCCESS,
            mode=WalkMode.CIRCULAR_RANDOM,
            coordinates=[[37.5, 127.0]],
        )]
        with patch("src.interfaces.dependencies.route_service", mock_service):
            response = client.post(
                "/api/walk/route",
                headers=headers,
                json={
                    "origin": {"lat": 37.5, "lon": 127.0},
                    "mode": "circular_random",
                },
            )

        assert response.status_code == 200
        assert mock_service.get_route.call_args.args[0] == expected_token

    def test_잘못된_인증_header가_있으면_유효한_cookie로_fallback하지_않는다(self, client):
        mock_service = MagicMock()
        with patch("src.interfaces.dependencies.route_service", mock_service):
            response = client.post(
                "/api/walk/route",
                headers={
                    "Authorization": "Basic malformed-token",
                    "Cookie": "access_token=valid-cookie-token",
                },
                json={
                    "origin": {"lat": 37.5, "lon": 127.0},
                    "mode": "circular_random",
                },
            )

        assert response.status_code == 401
        assert response.json() == {"detail": "invalid_token"}
        mock_service.get_route.assert_not_called()

    @pytest.mark.parametrize(
        ("bearer_token", "status"),
        [
            ("damaged-bearer", WalkRouteStatus.INVALID_TOKEN),
            ("expired-bearer", WalkRouteStatus.ACCESS_EXPIRED_TOKEN),
        ],
    )
    def test_유효한_cookie가_있어도_제공된_Bearer의_인증_결과를_사용한다(
        self, client, bearer_token, status
    ):
        mock_service = MagicMock()
        mock_service.get_route.return_value = [WalkRouteResponse(
            status=status,
            mode=WalkMode.CIRCULAR_RANDOM,
            coordinates=[],
        )]
        with patch("src.interfaces.dependencies.route_service", mock_service):
            response = client.post(
                "/api/walk/route",
                headers={
                    "Authorization": f"Bearer {bearer_token}",
                    "Cookie": "access_token=valid-cookie-token",
                },
                json={
                    "origin": {"lat": 37.5, "lon": 127.0},
                    "mode": "circular_random",
                },
            )

        assert response.status_code == 200
        assert response.json()["status"] == status.value
        assert mock_service.get_route.call_args.args[0] == bearer_token

    def test_토큰_누락은_None으로_기존_서비스_계약에_전달한다(self, client):
        mock_service = MagicMock()
        mock_service.get_route.return_value = [WalkRouteResponse(
            status=WalkRouteStatus.ACCESS_EXPIRED_TOKEN,
            mode=WalkMode.CIRCULAR_RANDOM,
            coordinates=[],
        )]
        with patch("src.interfaces.dependencies.route_service", mock_service):
            response = client.post(
                "/api/walk/route",
                json={
                    "origin": {"lat": 37.5, "lon": 127.0},
                    "mode": "circular_random",
                },
            )

        assert response.status_code == 200
        assert response.json()["status"] == "access_expired_token"
        assert mock_service.get_route.call_args.args[0] is None


# ── GET /api/auth/check/access_token ─────────────────────────────────────────


class TestAuthCheckAccessToken:
    def test_유효한_access_token이면_SUCCESS_반환(self, client, auth_service):
        token = auth_service.get_access_token(Provider.KAKAO, "42")
        mock_svc = MagicMock()
        mock_svc.check_access_token.return_value = (Status.SUCCESS, Provider.KAKAO, "42")
        with patch("src.interfaces.dependencies.auth_service", mock_svc):
            response = client.get(
                "/api/auth/check/access_token",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        mock_svc.check_access_token.assert_called_once_with(token)

    def test_만료된_access_token이면_ACCESS_EXPIRED_TOKEN_반환(self, client):
        mock_svc = MagicMock()
        mock_svc.check_access_token.return_value = (Status.ACCESS_EXPIRED_TOKEN, None, None)
        with patch("src.interfaces.dependencies.auth_service", mock_svc):
            response = client.get(
                "/api/auth/check/access_token",
                headers={"Authorization": "Bearer expired.token.value"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "access_expired_token"

    def test_잘못된_서명이면_INVALID_TOKEN_반환(self, client):
        mock_svc = MagicMock()
        mock_svc.check_access_token.return_value = (Status.INVALID_TOKEN, None, None)
        with patch("src.interfaces.dependencies.auth_service", mock_svc):
            response = client.get(
                "/api/auth/check/access_token",
                headers={"Authorization": "Bearer bad.token"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "invalid_token"

    def test_쿠키_없어도_200_반환(self, client):
        mock_svc = MagicMock()
        mock_svc.check_access_token.return_value = (Status.ACCESS_EXPIRED_TOKEN, None, None)
        with patch("src.interfaces.dependencies.auth_service", mock_svc):
            response = client.get("/api/auth/check/access_token")
        assert response.status_code == 200
        assert response.json()["status"] == "access_expired_token"


# ── GET /api/auth/check/refresh_token ────────────────────────────────────────


class TestAuthCheckRefreshToken:
    def test_유효한_refresh_token이면_새_access_token_쿠키_설정(
        self, client, auth_service
    ):
        new_access_token = auth_service.get_access_token(Provider.KAKAO, "42")
        mock_svc = MagicMock()
        mock_svc.check_refresh_token = AsyncMock(
            return_value=(Status.SUCCESS, new_access_token, "42")
        )
        with patch("src.interfaces.dependencies.auth_service", mock_svc):
            response = client.get(
                "/api/auth/check/refresh_token",
                headers={"Authorization": "Bearer valid.refresh.token"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        assert response.json()["access_token"] == new_access_token
        assert "access_token" in response.cookies

    def test_만료된_refresh_token이면_REFRESH_EXPIRED_TOKEN_반환(self, client):
        mock_svc = MagicMock()
        mock_svc.check_refresh_token = AsyncMock(
            return_value=(Status.REFRESH_EXPIRED_TOKEN, None, None)
        )
        with patch("src.interfaces.dependencies.auth_service", mock_svc):
            response = client.get(
                "/api/auth/check/refresh_token",
                headers={"Authorization": "Bearer expired.refresh.token"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "refresh_expired_token"
        assert response.json()["access_token"] is None


# ── POST /api/prewalk/init ───────────────────────────────────────────────────


class TestPrewalkInitAPI:
    def test_초기_메시지_요청_성공(self, client):
        from src.interfaces.schema.prewalk_schema import ChatResponse, ChatStatus
        from src.schema.prewalk_schema import State, Location

        mock_orchestrator = MagicMock()
        mock_orchestrator.get_init_message = AsyncMock(
            return_value=ChatResponse(
                status=ChatStatus.SUCCESS,
                thread_id="thread-abc-123",
                state=State(
                    user_id=1,
                    current_location=Location(lat=37.5, lon=127.0),
                ),
            )
        )
        with patch("src.interfaces.dependencies.prewalk_orchestrator", mock_orchestrator):
            response = client.post(
                "/api/prewalk/init",
                json={"lat": 37.5, "lon": 127.0},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["thread_id"] == "thread-abc-123"

    def test_필수_필드_누락_시_422_반환(self, client):
        response = client.post("/api/prewalk/init", json={})
        assert response.status_code == 422

    def test_서비스_내부_오류_시_500_반환(self, client):
        mock_orchestrator = MagicMock()
        mock_orchestrator.get_init_message = AsyncMock(
            side_effect=RuntimeError("DB 연결 실패")
        )
        with patch("src.interfaces.dependencies.prewalk_orchestrator", mock_orchestrator):
            response = client.post(
                "/api/prewalk/init",
                json={"lat": 37.5, "lon": 127.0},
            )
        assert response.status_code == 500
        assert response.json() == {"detail": "서버 내부 오류가 발생했습니다."}
        assert "DB 연결 실패" not in response.text

    @pytest.mark.parametrize(
        ("headers", "expected_token"),
        [
            ({"Authorization": "Bearer chatbot-bearer"}, "chatbot-bearer"),
            ({"Cookie": "access_token=chatbot-cookie"}, "chatbot-cookie"),
            (
                {
                    "Authorization": "Bearer chatbot-bearer",
                    "Cookie": "access_token=chatbot-cookie",
                },
                "chatbot-bearer",
            ),
        ],
    )
    def test_Bearer와_기존_cookie_access_token을_지원한다(
        self, client, headers, expected_token
    ):
        from src.interfaces.schema.prewalk_schema import ChatResponse, ChatStatus
        from src.schema.prewalk_schema import Location, State

        mock_orchestrator = MagicMock()
        mock_orchestrator.get_init_message = AsyncMock(
            return_value=ChatResponse(
                status=ChatStatus.SUCCESS,
                thread_id="thread-auth-123",
                state=State(
                    user_id=1,
                    current_location=Location(lat=37.5, lon=127.0),
                ),
            )
        )
        with patch("src.interfaces.dependencies.prewalk_orchestrator", mock_orchestrator):
            response = client.post(
                "/api/prewalk/init",
                headers=headers,
                json={"lat": 37.5, "lon": 127.0},
            )

        assert response.status_code == 200
        assert mock_orchestrator.get_init_message.await_args.args[0] == expected_token

    def test_잘못된_header는_챗봇에서도_유효한_cookie로_fallback하지_않는다(self, client):
        mock_orchestrator = MagicMock()
        with patch("src.interfaces.dependencies.prewalk_orchestrator", mock_orchestrator):
            response = client.post(
                "/api/prewalk/init",
                headers={
                    "Authorization": "Basic malformed-token",
                    "Cookie": "access_token=valid-cookie-token",
                },
                json={"lat": 37.5, "lon": 127.0},
            )

        assert response.status_code == 401
        assert response.json() == {"detail": "invalid_token"}
        mock_orchestrator.get_init_message.assert_not_called()

    def test_손상된_Bearer는_챗봇에서도_cookie보다_우선한다(self, client):
        from src.interfaces.schema.prewalk_schema import ChatResponse, ChatStatus

        mock_orchestrator = MagicMock()
        mock_orchestrator.get_init_message = AsyncMock(
            return_value=ChatResponse(status=ChatStatus.INVALID_TOKEN)
        )
        with patch("src.interfaces.dependencies.prewalk_orchestrator", mock_orchestrator):
            response = client.post(
                "/api/prewalk/init",
                headers={
                    "Authorization": "Bearer damaged-chatbot-token",
                    "Cookie": "access_token=valid-cookie-token",
                },
                json={"lat": 37.5, "lon": 127.0},
            )

        assert response.status_code == 200
        assert response.json()["status"] == "invalid_token"
        assert mock_orchestrator.get_init_message.await_args.args[0] == "damaged-chatbot-token"


# ── POST /api/prewalk/intent ─────────────────────────────────────────────────


class TestPrewalkIntentAPI:
    def test_챗봇_대화_요청_성공(self, client):
        from src.interfaces.schema.prewalk_schema import ChatResponse, ChatStatus
        from src.schema.prewalk_schema import State, Location

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrator = AsyncMock(
            return_value=ChatResponse(
                status=ChatStatus.SUCCESS,
                thread_id="thread-abc-123",
                state=State(
                    user_id=1,
                    current_location=Location(lat=37.5, lon=127.0),
                    access_token="secret-ro-udi-access-token",
                ),
            )
        )
        with patch("src.interfaces.dependencies.prewalk_orchestrator", mock_orchestrator):
            response = client.post(
                "/api/prewalk/intent",
                json={
                    "thread_id": "thread-abc-123",
                    "user_prompt": "한강 근처로 3km 산책하고 싶어요",
                    "lat": 37.5,
                    "lon": 127.0,
                },
            )
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        assert response.json()["thread_id"] == "thread-abc-123"
        assert "access_token" not in response.json()["state"]
        assert "secret-ro-udi-access-token" not in response.text

    def test_필수_필드_누락_시_422_반환(self, client):
        response = client.post(
            "/api/prewalk/intent", json={"thread_id": "thread-abc-123"}
        )
        assert response.status_code == 422

    def test_공백_user_prompt_시_422_반환(self, client):
        response = client.post(
            "/api/prewalk/intent",
            json={"thread_id": "thread-abc-123", "user_prompt": "   ", "lat": 37.5, "lon": 127.0},
        )
        assert response.status_code == 422

    def test_존재하지_않는_thread_id_시_session_not_found_반환(self, client):
        from src.interfaces.schema.prewalk_schema import ChatResponse, ChatStatus

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrator = AsyncMock(
            return_value=ChatResponse(status=ChatStatus.SESSION_NOT_FOUND, thread_id=None, state=None)
        )
        with patch("src.interfaces.dependencies.prewalk_orchestrator", mock_orchestrator):
            response = client.post(
                "/api/prewalk/intent",
                json={"thread_id": "invalid-thread", "user_prompt": "산책 추천해줘", "lat": 37.5, "lon": 127.0},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "session_not_found"

    def test_다른_사용자의_대화_세션은_unaccessible을_유지한다(self, client):
        from src.interfaces.schema.prewalk_schema import ChatResponse, ChatStatus

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrator = AsyncMock(
            return_value=ChatResponse(
                status=ChatStatus.UNACCESSIBLE,
                thread_id=None,
                state=None,
            )
        )
        with patch("src.interfaces.dependencies.prewalk_orchestrator", mock_orchestrator):
            response = client.post(
                "/api/prewalk/intent",
                headers={"Authorization": "Bearer another-user-token"},
                json={
                    "thread_id": "other-users-thread",
                    "user_prompt": "이 경로를 보여줘",
                    "lat": 37.5,
                    "lon": 127.0,
                },
            )

        assert response.status_code == 200
        assert response.json()["status"] == "unaccessible"

    def test_서비스_내부_오류_시_500_반환(self, client):
        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrator = AsyncMock(
            side_effect=RuntimeError("LLM 호출 실패")
        )
        with patch("src.interfaces.dependencies.prewalk_orchestrator", mock_orchestrator):
            response = client.post(
                "/api/prewalk/intent",
                json={"thread_id": "thread-abc-123", "user_prompt": "산책 추천해줘", "lat": 37.5, "lon": 127.0},
            )
        assert response.status_code == 500
        assert response.json() == {"detail": "서버 내부 오류가 발생했습니다."}
        assert "LLM 호출 실패" not in response.text


# ── GET /api/map/facilities ──────────────────────────────────────────────────


class TestMapFacilitiesAPI:
    def test_시설_조회_성공(self, client):
        mock_places = [
            MagicMock(
                place_name="편의점A",
                x="127.01",
                y="37.51",
                address_name="서울시 광진구",
            ),
            MagicMock(
                place_name="카페B", x="127.02", y="37.52", address_name="서울시 광진구"
            ),
        ]
        mock_service = MagicMock()
        mock_service.fetch_kakao_facilities = AsyncMock(return_value=mock_places)
        with patch("src.interfaces.dependencies.map_service", mock_service):
            response = client.get(
                "/api/map/facilities",
                params={"lat": 37.5, "lon": 127.0, "radius": 1000},
            )
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 2
        assert body[0]["name"] == "편의점A"
        assert "lat" in body[0]
        assert "lon" in body[0]

    def test_lat_lon_누락_시_422_반환(self, client):
        response = client.get("/api/map/facilities", params={"radius": 1000})
        assert response.status_code == 422

    def test_서비스_오류_시_500_반환(self, client):
        mock_service = MagicMock()
        mock_service.fetch_kakao_facilities = AsyncMock(
            side_effect=Exception("카카오 API 오류")
        )
        with patch("src.interfaces.dependencies.map_service", mock_service):
            response = client.get(
                "/api/map/facilities", params={"lat": 37.5, "lon": 127.0}
            )
        assert response.status_code == 500
        assert response.json() == {"detail": "서버 내부 오류가 발생했습니다."}
        assert "카카오 API 오류" not in response.text


# ── GET /api/map/points ──────────────────────────────────────────────────────


class TestMapPointsAPI:
    def test_안전_포인트_레이어_조회_성공(self, client):
        import pandas as pd

        mock_df = pd.DataFrame(
            [
                {"lat": 37.51, "lon": 127.01, "category": "cctv"},
                {"lat": 37.52, "lon": 127.02, "category": "streetlight"},
            ]
        )
        mock_service = MagicMock()
        mock_service.fetch_safety_points.return_value = mock_df
        with patch("src.interfaces.dependencies.map_service", mock_service):
            response = client.get(
                "/api/map/points/safety",
                params={"lat": 37.5, "lon": 127.0},
            )
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 2
        assert "lat" in body[0]
        assert "category" in body[0]

    def test_지원하지_않는_레이어_경로면_404_반환(self, client):
        mock_service = MagicMock()
        with patch("src.interfaces.dependencies.map_service", mock_service):
            response = client.get(
                "/api/map/points/invalid_layer",
                params={"lat": 37.5, "lon": 127.0},
            )
        assert response.status_code == 404


# ── GET /api/map/edges ───────────────────────────────────────────────────────


class TestMapEdgesAPI:
    def test_엣지_레이어_조회_성공(self, client):
        import pandas as pd
        import json

        mock_df = pd.DataFrame(
            [
                {
                    "geometry": json.dumps(
                        {"coordinates": [[127.0, 37.5], [127.01, 37.51]]}
                    ),
                    "link_id": "edge-001",
                }
            ]
        )
        mock_service = MagicMock()
        mock_service.fetch_db_lines.return_value = mock_df
        with patch("src.interfaces.dependencies.map_service", mock_service):
            response = client.get(
                "/api/map/edges", params={"lat": 37.5, "lon": 127.0, "radius_m": 2000}
            )
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert "path" in body[0]
        assert "link_id" in body[0]
        assert body[0]["link_id"] == "edge-001"

    def test_결과_없으면_빈_리스트_반환(self, client):
        import pandas as pd

        mock_service = MagicMock()
        mock_service.fetch_db_lines.return_value = pd.DataFrame()
        with patch("src.interfaces.dependencies.map_service", mock_service):
            response = client.get("/api/map/edges", params={"lat": 37.5, "lon": 127.0})
        assert response.status_code == 200
        assert response.json() == []

    def test_lat_lon_누락_시_422_반환(self, client):
        response = client.get("/api/map/edges")
        assert response.status_code == 422


# ── POST /api/user/survey ────────────────────────────────────────────────────

class TestSurveyAPI:
    def test_설문_정상_제출(self, client):
        mock_service = MagicMock()
        mock_service.submit.return_value = SurveyResponse(
            status=SurveyStatus.SUCCESS,
            default_target_km=3.0,
            weights_safety=0.7,
            weights_comfort=0.2667,
        )
        with patch("src.interfaces.dependencies.survey_service", mock_service):
            response = client.post(
                "/api/user/survey",
                json={
                    "tags": ["안전"],
                    "distance": "normal",
                },
            )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["default_target_km"] == 3.0
        assert body["weights_safety"] == 0.7
        assert body["weights_comfort"] == 0.2667

    def test_태그_없이_제출하면_성공(self, client):
        mock_service = MagicMock()
        mock_service.submit.return_value = SurveyResponse(
            status=SurveyStatus.SUCCESS,
        )
        with patch("src.interfaces.dependencies.survey_service", mock_service):
            response = client.post("/api/user/survey", json={})
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    def test_만료된_토큰이면_ACCESS_EXPIRED_TOKEN_반환(self, client):
        mock_service = MagicMock()
        mock_service.submit.return_value = SurveyResponse(
            status=SurveyStatus.ACCESS_EXPIRED_TOKEN,
        )
        with patch("src.interfaces.dependencies.survey_service", mock_service):
            response = client.post(
                "/api/user/survey",
                json={"tags": []},
                cookies={"access_token": "expired.token"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "access_expired_token"

    def test_유효하지_않은_distance_값이면_422_반환(self, client):
        response = client.post(
            "/api/user/survey",
            json={"tags": [], "distance": "invalid_option"},
        )
        assert response.status_code == 422


class TestUserRouteOwnership:
    def test_다른_사용자의_경로_id는_현재_사용자_id로_조회해_404를_반환한다(self, client):
        mock_auth = MagicMock()
        mock_auth.check_access_token.return_value = (
            Status.SUCCESS,
            Provider.KAKAO,
            "request-user",
        )
        user = MagicMock(id=10)
        with patch("src.interfaces.dependencies.auth_service", mock_auth), patch(
            "src.interfaces.api.user_router.UserRepository.find_by_provider_and_provider_id",
            return_value=user,
        ), patch(
            "src.interfaces.api.user_router.RouteHistoryRepository.find_by_id",
            return_value=None,
        ) as find_history:
            response = client.get(
                "/api/user/routes/999",
                headers={"Authorization": "Bearer request-user-token"},
            )

        assert response.status_code == 404
        find_history.assert_called_once_with(999, 10)

    def test_경로_조회_내부_오류는_예외_원문을_노출하지_않는다(self, client):
        mock_auth = MagicMock()
        mock_auth.check_access_token.return_value = (
            Status.SUCCESS,
            Provider.KAKAO,
            "request-user",
        )
        with patch("src.interfaces.dependencies.auth_service", mock_auth), patch(
            "src.interfaces.api.user_router.UserRepository.find_by_provider_and_provider_id",
            return_value=MagicMock(id=10),
        ), patch(
            "src.interfaces.api.user_router.RouteHistoryRepository.find_by_id",
            side_effect=RuntimeError("postgresql://user:secret@internal-db"),
        ):
            response = client.get(
                "/api/user/routes/999",
                headers={"Authorization": "Bearer request-user-token"},
            )

        assert response.status_code == 500
        assert response.json() == {"detail": "서버 내부 오류가 발생했습니다."}
        assert "secret" not in response.text


class TestUnhandledErrorSafety:
    def test_처리되지_않은_로그인_예외도_안전한_JSON_500을_반환한다(self, client):
        mock_login = MagicMock()
        mock_login.login_with_access_token = AsyncMock(
            side_effect=RuntimeError("upstream token=secret-kakao-token")
        )
        with patch("src.interfaces.dependencies.kakao_login_service", mock_login):
            response = client.post(
                "/api/login/kakao/mobile-login",
                json={"access_token": "secret-kakao-token"},
            )

        assert response.status_code == 500
        assert response.json() == {"detail": "서버 내부 오류가 발생했습니다."}
        assert "secret-kakao-token" not in response.text


class TestOpenAPIContract:
    def test_access와_refresh_Bearer_scheme이_구분된다(self, client):
        schema = client.get("/openapi.json").json()
        schemes = schema["components"]["securitySchemes"]

        assert set(schemes) >= {"AccessTokenBearer", "RefreshTokenBearer"}
        assert "access token" in schemes["AccessTokenBearer"]["description"]
        assert "refresh token" in schemes["RefreshTokenBearer"]["description"]
        assert schema["paths"]["/api/auth/check/access_token"]["get"]["security"] == [
            {"AccessTokenBearer": []}
        ]
        assert schema["paths"]["/api/auth/check/refresh_token"]["get"]["security"] == [
            {"RefreshTokenBearer": []}
        ]

    @pytest.mark.parametrize(
        ("path", "method"),
        [
            ("/api/walk/route", "post"),
            ("/api/prewalk/init", "post"),
            ("/api/prewalk/intent", "post"),
            ("/api/user/survey", "post"),
        ],
    )
    def test_보호_API는_access_Bearer와_호환_cookie를_문서화한다(
        self, client, path, method
    ):
        operation = client.get("/openapi.json").json()["paths"][path][method]

        assert operation["security"] == [{"AccessTokenBearer": []}]
        cookie = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["in"] == "cookie" and parameter["name"] == "access_token"
        )
        assert cookie["required"] is False

    def test_프론트_입력_제약과_예제가_OpenAPI에_반영된다(self, client):
        schema = client.get("/openapi.json").json()
        models = schema["components"]["schemas"]

        target = models["WalkRouteRequest"]["properties"]["target_km"]["anyOf"][0]
        assert target["exclusiveMinimum"] == 0.0
        assert target["maximum"] == 10.0
        assert models["WalkRouteRequest"]["example"]["target_km"] == 3.0
        assert models["SurveyRequest"]["example"]["tags"] == ["안전한 길", "편안한 길"]
        assert "Kakao SDK" in models["MobileLoginRequest"]["properties"]["access_token"]["description"]
        assert "access_token" not in models["State"]["properties"]

        walk_responses = schema["paths"]["/api/walk/route"]["post"]["responses"]
        assert set(walk_responses) >= {"200", "400", "401", "422", "500"}
