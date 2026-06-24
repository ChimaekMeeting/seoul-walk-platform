"""
tests/unit/test_routue_service.py
RouteService 단위 테스트 (3모드: circular_random / oneway_shortest / oneway_random)
"""

import pytest
import networkx as nx
from unittest.mock import MagicMock, patch

from src.service.route.route_service import RouteService
from src.interfaces.schema.walk_schema import (
    WalkMode,
    Coordinate,
    FallbackReason,
    WalkRouteResponse,
)
from src.interfaces.schema.auth_schema import Status

# ── 공통 픽스처 ──────────────────────────────────────────────────────────────

ACCESS_TOKEN = "valid-token"
ORIGIN = Coordinate(lat=37.5, lon=127.0)
DEST = Coordinate(lat=37.6, lon=127.1)

SUCCESS_RESPONSE = WalkRouteResponse(
    status="SUCCESS",
    mode=WalkMode.CIRCULAR_RANDOM,
    coordinates=[[37.5, 127.0], [37.51, 127.01]],
    total_km=1.5,
)

FAILED_RESPONSE = WalkRouteResponse(
    status="FAILED",
    mode=WalkMode.CIRCULAR_RANDOM,
    coordinates=[],
    total_km=0.0,
    fallback_reason=FallbackReason.NO_PATH,
)


@pytest.fixture
def empty_graph():
    return nx.Graph()


@pytest.fixture
def auth_service():
    """기본적으로 인증 성공을 반환하는 AuthService 목."""
    mock = MagicMock()
    mock.check_access_token.return_value = (Status.SUCCESS, None, None)
    return mock


@pytest.fixture
def service(empty_graph, auth_service):
    return RouteService(empty_graph, auth_service)


@pytest.fixture
def patched_nodes():
    """origin/destination 보행 노드 탐색이 항상 성공하도록 PathUtils를 패치."""
    with patch("src.service.route.route_service.PathUtils") as MockPathUtils:
        MockPathUtils.return_value.find_nearest_node_with_expansion.return_value = 1
        yield MockPathUtils


# ── 인증 ─────────────────────────────────────────────────────────────────────


class TestAuthFailure:
    def test_인증_실패시_FAILED를_반환한다(self, service, auth_service):
        auth_service.check_access_token.return_value = (Status.ACCESS_EXPIRED_TOKEN, None, None)

        result = service.get_route(ACCESS_TOKEN, ORIGIN, mode=WalkMode.CIRCULAR_RANDOM)

        assert result.status == "FAILED"
        assert result.fallback_reason == FallbackReason.ACCESS_EXPIRED_TOKEN


# ── 알 수 없는 모드 ──────────────────────────────────────────────────────────
# WalkMode가 아닌 임의 문자열을 넣으면 base_engines에 없어 FAILED 응답을 만들려다
# WalkRouteResponse(mode=<invalid>) 생성 시 Pydantic ValidationError가 발생한다.
# (현재 동작 고정 — 정상 입력은 항상 WalkMode 열거형이라 도달 불가 경로)


class TestUnknownMode:
    def test_알_수_없는_모드는_예외를_발생시킨다(self, service):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            service.get_route(ACCESS_TOKEN, ORIGIN, mode="invalid_mode")


# ── 편도 모드 destination 누락 ────────────────────────────────────────────────


class TestOnewayWithoutDestination:
    @pytest.mark.parametrize(
        "mode",
        [
            WalkMode.ONEWAY_SHORTEST,
            WalkMode.ONEWAY_RANDOM,
        ],
    )
    def test_편도_모드에_destination_없으면_FAILED를_반환한다(self, service, patched_nodes, mode):
        result = service.get_route(ACCESS_TOKEN, ORIGIN, mode=mode)

        assert result.status == "FAILED"
        assert result.fallback_reason == FallbackReason.INVALID_DESTINATION


# ── 모드별 엔진 라우팅 ────────────────────────────────────────────────────────
# base_engines 딕셔너리의 엔진 클래스를 목으로 교체해 라우팅을 검증한다.


class TestModeRouting:
    @pytest.mark.parametrize(
        "mode,destination",
        [
            (WalkMode.CIRCULAR_RANDOM, None),
            (WalkMode.ONEWAY_SHORTEST, DEST),
            (WalkMode.ONEWAY_RANDOM, DEST),
        ],
    )
    def test_모드에_맞는_엔진이_호출된다(self, service, patched_nodes, mode, destination):
        mock_engine_instance = MagicMock()
        mock_engine_instance.run.return_value = SUCCESS_RESPONSE
        MockEngineClass = MagicMock(return_value=mock_engine_instance)

        service.base_engines[mode] = MockEngineClass
        service.get_route(ACCESS_TOKEN, ORIGIN, destination=destination, target_km=3.0, mode=mode)

        MockEngineClass.assert_called_once()

    def test_엔진의_run_결과가_그대로_반환된다(self, service, patched_nodes):
        mock_engine_instance = MagicMock()
        mock_engine_instance.run.return_value = SUCCESS_RESPONSE
        MockEngineClass = MagicMock(return_value=mock_engine_instance)

        service.base_engines[WalkMode.CIRCULAR_RANDOM] = MockEngineClass
        result = service.get_route(ACCESS_TOKEN, ORIGIN, target_km=3.0, mode=WalkMode.CIRCULAR_RANDOM)

        assert result.status == "SUCCESS"
        assert result.total_km == 1.5

    def test_엔진이_FAILED를_반환하면_그대로_전달된다(self, service, patched_nodes):
        mock_engine_instance = MagicMock()
        mock_engine_instance.run.return_value = FAILED_RESPONSE
        MockEngineClass = MagicMock(return_value=mock_engine_instance)

        service.base_engines[WalkMode.CIRCULAR_RANDOM] = MockEngineClass
        result = service.get_route(ACCESS_TOKEN, ORIGIN, target_km=3.0, mode=WalkMode.CIRCULAR_RANDOM)

        assert result.status == "FAILED"
        assert result.fallback_reason == FallbackReason.NO_PATH
