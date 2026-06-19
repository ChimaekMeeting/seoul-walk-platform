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
    CircularMode,
    FallbackReason,
)
from src.interfaces.schema.auth_schema import Status
from src.service.user.auth_service import AuthService

# ── 공통 픽스처 ──────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
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
        mock_service.get_route.return_value = WalkRouteResponse(
            status="SUCCESS",
            mode=CircularMode.RANDOM,
            coordinates=[[37.5, 127.0], [37.51, 127.01], [37.5, 127.0]],
            total_km=3.1,
        )
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
        assert body["status"] == "SUCCESS"
        assert body["mode"] == "circular_random"
        assert len(body["coordinates"]) > 0
        assert body["total_km"] == 3.1

    def test_편도_최단_경로_요청_성공(self, client):
        mock_service = MagicMock()
        mock_service.get_route.return_value = WalkRouteResponse(
            status="SUCCESS",
            mode="oneway_shortest",
            coordinates=[[37.5, 127.0], [37.55, 127.05], [37.6, 127.1]],
            total_km=7.2,
        )
        with patch("src.interfaces.dependencies.route_service", mock_service):
            response = client.post(
                "/api/walk/route",
                json={
                    "origin": {"lat": 37.5, "lon": 127.0},
                    "destination": {"lat": 37.6, "lon": 127.1},
                    "mode": "oneway_shortest",
                },
            )
        assert response.status_code == 200
        assert response.json()["status"] == "SUCCESS"

    def test_경로_생성_실패_시_FAILED_반환(self, client):
        mock_service = MagicMock()
        mock_service.get_route.return_value = WalkRouteResponse(
            status="FAILED",
            mode=CircularMode.RANDOM,
            coordinates=[],
            total_km=0.0,
            fallback_reason=FallbackReason.NO_NEAREST_START_NODE,
        )
        with patch("src.interfaces.dependencies.route_service", mock_service):
            response = client.post(
                "/api/walk/route",
                json={
                    "origin": {"lat": 0.0, "lon": 0.0},
                    "mode": "circular_random",
                },
            )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "FAILED"
        assert body["fallback_reason"] == "NO_NEAREST_START_NODE"

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


# ── GET /api/auth/check/access_token ─────────────────────────────────────────


class TestAuthCheckAccessToken:
    def test_유효한_access_token이면_SUCCESS_반환(self, client, auth_service):
        token = auth_service.get_access_token(42)
        mock_svc = MagicMock()
        mock_svc.check_access_token.return_value = (Status.SUCCESS, 42)
        with patch("src.interfaces.dependencies.auth_service", mock_svc):
            response = client.get(
                "/api/auth/check/access_token",
                cookies={"access_token": token},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    def test_만료된_access_token이면_ACCESS_EXPIRED_TOKEN_반환(self, client):
        mock_svc = MagicMock()
        mock_svc.check_access_token.return_value = (Status.ACCESS_EXPIRED_TOKEN, None)
        with patch("src.interfaces.dependencies.auth_service", mock_svc):
            response = client.get(
                "/api/auth/check/access_token",
                cookies={"access_token": "expired.token.value"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "access_expired_token"

    def test_잘못된_서명이면_INVALID_TOKEN_반환(self, client):
        mock_svc = MagicMock()
        mock_svc.check_access_token.return_value = (Status.INVALID_TOKEN, None)
        with patch("src.interfaces.dependencies.auth_service", mock_svc):
            response = client.get(
                "/api/auth/check/access_token",
                cookies={"access_token": "bad.token"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "invalid_token"

    def test_쿠키_없어도_200_반환(self, client):
        mock_svc = MagicMock()
        mock_svc.check_access_token.return_value = (Status.INVALID_TOKEN, None)
        with patch("src.interfaces.dependencies.auth_service", mock_svc):
            response = client.get("/api/auth/check/access_token")
        assert response.status_code == 200


# ── GET /api/auth/check/refresh_token ────────────────────────────────────────


class TestAuthCheckRefreshToken:
    def test_유효한_refresh_token이면_새_access_token_쿠키_설정(
        self, client, auth_service
    ):
        new_access_token = auth_service.get_access_token(42)
        mock_svc = MagicMock()
        mock_svc.check_refresh_token.return_value = (
            Status.SUCCESS,
            new_access_token,
            42,
        )
        with patch("src.interfaces.dependencies.auth_service", mock_svc):
            response = client.get(
                "/api/auth/check/refresh_token",
                cookies={"refresh_token": "valid.refresh.token"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        assert "access_token" in response.cookies

    def test_만료된_refresh_token이면_REFRESH_EXPIRED_TOKEN_반환(self, client):
        mock_svc = MagicMock()
        mock_svc.check_refresh_token.return_value = (
            Status.REFRESH_EXPIRED_TOKEN,
            None,
            None,
        )
        with patch("src.interfaces.dependencies.auth_service", mock_svc):
            response = client.get(
                "/api/auth/check/refresh_token",
                cookies={"refresh_token": "expired.refresh.token"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "refresh_expired_token"


# ── POST /api/prewalk/init ───────────────────────────────────────────────────


class TestPrewalkInitAPI:
    def test_초기_메시지_요청_성공(self, client):
        from src.schema.prewalk_schema import State

        mock_orchestrator = MagicMock()
        mock_orchestrator.get_init_message = AsyncMock(
            return_value={
                "thread_id": "thread-abc-123",
                "state": State(
                    user_uuid="user-uuid-001",
                    current_location={"lat": 37.5, "lon": 127.0},
                ),
            }
        )
        with patch(
            "src.interfaces.dependencies.prewalk_orchestrator", mock_orchestrator
        ):
            response = client.post(
                "/api/prewalk/init",
                json={
                    "user_uuid": "user-uuid-001",
                    "lat": 37.5,
                    "lon": 127.0,
                },
            )
        assert response.status_code == 200
        body = response.json()
        assert "thread_id" in body
        assert body["thread_id"] == "thread-abc-123"

    def test_필수_필드_누락_시_422_반환(self, client):
        response = client.post("/api/prewalk/init", json={"user_uuid": "user-uuid-001"})
        assert response.status_code == 422


# ── POST /api/prewalk/intent ─────────────────────────────────────────────────


class TestPrewalkIntentAPI:
    def test_챗봇_대화_요청_성공(self, client):
        from src.schema.prewalk_schema import State

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrator = AsyncMock(
            return_value={
                "thread_id": "thread-abc-123",
                "state": State(
                    user_uuid="user-uuid-001",
                    current_location={"lat": 37.5, "lon": 127.0},
                ),
            }
        )
        with patch(
            "src.interfaces.dependencies.prewalk_orchestrator", mock_orchestrator
        ):
            response = client.post(
                "/api/prewalk/intent",
                json={
                    "thread_id": "thread-abc-123",
                    "user_prompt": "한강 근처로 3km 산책하고 싶어요",
                },
            )
        assert response.status_code == 200
        assert response.json()["thread_id"] == "thread-abc-123"

    def test_필수_필드_누락_시_422_반환(self, client):
        response = client.post(
            "/api/prewalk/intent", json={"thread_id": "thread-abc-123"}
        )
        assert response.status_code == 422


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


# ── GET /api/map/points ──────────────────────────────────────────────────────


class TestMapPointsAPI:
    def test_포인트_레이어_조회_성공(self, client):
        import pandas as pd

        mock_df = pd.DataFrame(
            [
                {"lat": 37.51, "lon": 127.01},
                {"lat": 37.52, "lon": 127.02},
            ]
        )
        mock_service = MagicMock()
        mock_service.fetch_db_points.return_value = mock_df
        with patch("src.interfaces.dependencies.map_service", mock_service):
            response = client.get(
                "/api/map/points",
                params={"lat": 37.5, "lon": 127.0, "table_name": "child_layer"},
            )
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 2
        assert "lat" in body[0]

    def test_지원하지_않는_table_name이면_400_반환(self, client):
        mock_service = MagicMock()
        mock_service.fetch_db_points.side_effect = ValueError("지원하지 않는 테이블")
        with patch("src.interfaces.dependencies.map_service", mock_service):
            response = client.get(
                "/api/map/points",
                params={"lat": 37.5, "lon": 127.0, "table_name": "invalid_table"},
            )
        assert response.status_code == 400


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
