"""
tests/unit/test_route_service.py
RouteService 단위 테스트
"""

import pytest
import networkx as nx
from unittest.mock import MagicMock

from src.service.route.route_service import RouteService
from src.interfaces.schema.walk_schema import (
    CircularMode,
    OnewayMode,
    Coordinate,
    WalkRouteStatus,
    WalkRouteResponse,
)
from src.interfaces.schema.auth_schema import Status

# ── 공통 픽스처 ──────────────────────────────────────────────────────────────


@pytest.fixture
def empty_graph():
    """
    완전히 빈 그래프는 PathUtils.find_nearest_node()의 connected_components
    탐색에서 ValueError를 일으키므로, 보행 노드 선행 검증(ROUT-NODE-001/002)을
    통과할 수 있게 출발/도착 좌표 근처에 노드를 하나씩 둔다.
    """
    G = nx.Graph()
    G.add_node(1, lat=37.5, lon=127.0)
    G.add_node(2, lat=37.6, lon=127.1)
    G.add_edge(1, 2, length=1000)
    return G


@pytest.fixture
def auth_service():
    mock = MagicMock()
    mock.check_access_token.return_value = (Status.SUCCESS, None, None)
    return mock


@pytest.fixture
def service(empty_graph, auth_service):
    return RouteService(empty_graph, auth_service)


ACCESS_TOKEN = "dummy-access-token"
ORIGIN = Coordinate(lat=37.5, lon=127.0)
DEST = Coordinate(lat=37.6, lon=127.1)

SUCCESS_RESPONSE = WalkRouteResponse(
    status=WalkRouteStatus.SUCCESS,
    mode=CircularMode.RANDOM,
    coordinates=[[37.5, 127.0], [37.51, 127.01]],
    total_km=1.5,
)

FAILED_RESPONSE = WalkRouteResponse(
    status=WalkRouteStatus.NO_PATH,
    mode=CircularMode.RANDOM,
    coordinates=[],
    total_km=0.0,
)


# ── 인증 실패 ────────────────────────────────────────────────────────────────


class TestAuthFailure:
    def test_토큰이_만료되면_access_expired_token_status를_반환한다(self, service, auth_service):
        auth_service.check_access_token.return_value = (Status.ACCESS_EXPIRED_TOKEN, None, None)
        result = service.get_route(ACCESS_TOKEN, origin=ORIGIN, mode=CircularMode.RANDOM)
        assert result.status == WalkRouteStatus.ACCESS_EXPIRED_TOKEN

    def test_토큰이_유효하지_않으면_invalid_token_status를_반환한다(self, service, auth_service):
        auth_service.check_access_token.return_value = (Status.INVALID_TOKEN, None, None)
        result = service.get_route(ACCESS_TOKEN, origin=ORIGIN, mode=CircularMode.RANDOM)
        assert result.status == WalkRouteStatus.INVALID_TOKEN


# ── 알 수 없는 모드 ──────────────────────────────────────────────────────────


class TestUnknownMode:
    def test_알_수_없는_모드는_예외를_발생시킨다(self, service):
        """
        [이슈] RouteService.get_route()에 알 수 없는 모드가 전달되면
        WalkRouteResponse(mode=invalid_mode) 생성 시 Pydantic ValidationError 발생.
        mode 필드가 Union[CircularMode, OnewayMode]로 타입 제한되어 있어
        임의 문자열을 넣으면 터짐. → 담당자 이슈 전달 필요.
        """
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            service.get_route(ACCESS_TOKEN, origin=ORIGIN, mode="invalid_mode")


# ── 편도 모드 destination 누락 ────────────────────────────────────────────────


class TestOnewayWithoutDestination:
    def test_편도_모드에_destination_없으면_invalid_destination을_반환한다(self, service):
        result = service.get_route(ACCESS_TOKEN, origin=ORIGIN, mode=OnewayMode.SHORTEST)
        assert result.status == WalkRouteStatus.INVALID_DESTINATION

    @pytest.mark.parametrize(
        "mode",
        [
            OnewayMode.SHORTEST,
            OnewayMode.RANDOM,
            OnewayMode.CHILD,
            OnewayMode.RUNNING,
        ],
    )
    def test_모든_편도_모드에서_destination_없으면_실패_status다(self, service, mode):
        result = service.get_route(ACCESS_TOKEN, origin=ORIGIN, mode=mode)
        assert result.status != WalkRouteStatus.SUCCESS


# ── 순환 모드 엔진 라우팅 ────────────────────────────────────────────────────
# patch()는 이미 딕셔너리에 들어간 클래스를 못 바꿔요.
# service._circular_engines 딕셔너리를 직접 교체하는 방식으로 테스트해요.


class TestCircularModeRouting:
    @pytest.mark.parametrize(
        "mode",
        [
            CircularMode.RANDOM,
            CircularMode.CHILD,
            CircularMode.RUNNING,
        ],
    )
    def test_순환_모드에_맞는_엔진이_호출된다(self, service, mode):
        mock_engine_instance = MagicMock()
        mock_engine_instance.run.return_value = SUCCESS_RESPONSE
        MockEngineClass = MagicMock(return_value=mock_engine_instance)

        service._circular_engines[mode] = MockEngineClass
        service.get_route(ACCESS_TOKEN, origin=ORIGIN, mode=mode, target_km=3.0)

        MockEngineClass.assert_called_once()

    def test_순환_모드_엔진의_run_결과가_그대로_반환된다(self, service):
        mock_engine_instance = MagicMock()
        mock_engine_instance.run.return_value = SUCCESS_RESPONSE
        MockEngineClass = MagicMock(return_value=mock_engine_instance)

        service._circular_engines[CircularMode.RANDOM] = MockEngineClass
        result = service.get_route(ACCESS_TOKEN, origin=ORIGIN, mode=CircularMode.RANDOM)

        assert result.status == WalkRouteStatus.SUCCESS
        assert result.total_km == 1.5

    def test_엔진이_실패_status를_반환하면_그대로_전달된다(self, service):
        mock_engine_instance = MagicMock()
        mock_engine_instance.run.return_value = FAILED_RESPONSE
        MockEngineClass = MagicMock(return_value=mock_engine_instance)

        service._circular_engines[CircularMode.RANDOM] = MockEngineClass
        result = service.get_route(ACCESS_TOKEN, origin=ORIGIN, mode=CircularMode.RANDOM)

        assert result.status == WalkRouteStatus.NO_PATH


# ── 편도 모드 엔진 라우팅 ────────────────────────────────────────────────────


class TestOnewayModeRouting:
    @pytest.mark.parametrize(
        "mode",
        [
            OnewayMode.SHORTEST,
            OnewayMode.RANDOM,
            OnewayMode.CHILD,
            OnewayMode.RUNNING,
        ],
    )
    def test_편도_모드에_맞는_엔진이_호출된다(self, service, mode):
        mock_engine_instance = MagicMock()
        mock_engine_instance.run.return_value = SUCCESS_RESPONSE
        MockEngineClass = MagicMock(return_value=mock_engine_instance)

        service._oneway_engines[mode] = MockEngineClass
        service.get_route(ACCESS_TOKEN, origin=ORIGIN, destination=DEST, mode=mode)

        MockEngineClass.assert_called_once()

    def test_편도_모드_엔진의_run_결과가_그대로_반환된다(self, service):
        mock_engine_instance = MagicMock()
        mock_engine_instance.run.return_value = SUCCESS_RESPONSE
        MockEngineClass = MagicMock(return_value=mock_engine_instance)

        service._oneway_engines[OnewayMode.SHORTEST] = MockEngineClass
        result = service.get_route(
            ACCESS_TOKEN, origin=ORIGIN, destination=DEST, mode=OnewayMode.SHORTEST
        )

        assert result.status == WalkRouteStatus.SUCCESS
