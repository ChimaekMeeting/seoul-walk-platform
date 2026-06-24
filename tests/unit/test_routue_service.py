"""
tests/unit/test_routue_service.py
RouteService unit tests for the three supported walk modes.
"""

from unittest.mock import MagicMock, patch

import networkx as nx
import pytest

from src.interfaces.schema.auth_schema import Status
from src.interfaces.schema.walk_schema import (
    Coordinate,
    WalkMode,
    WalkRouteResponse,
    WalkRouteStatus,
)
from src.service.route.route_service import RouteService


ACCESS_TOKEN = "valid-token"
ORIGIN = Coordinate(lat=37.5, lon=127.0)
DEST = Coordinate(lat=37.6, lon=127.1)

SUCCESS_RESPONSE = WalkRouteResponse(
    status=WalkRouteStatus.SUCCESS,
    mode=WalkMode.CIRCULAR_RANDOM,
    coordinates=[[37.5, 127.0], [37.51, 127.01]],
    total_km=1.5,
)

FAILED_RESPONSE = WalkRouteResponse(
    status=WalkRouteStatus.NO_PATH,
    mode=WalkMode.CIRCULAR_RANDOM,
    coordinates=[],
    total_km=0.0,
)


@pytest.fixture
def empty_graph():
    """
    Keep a minimal graph so RouteService's nearest-node precheck can pass
    before mocked engines are invoked.
    """
    graph = nx.Graph()
    graph.add_node(1, lat=37.5, lon=127.0)
    graph.add_node(2, lat=37.6, lon=127.1)
    graph.add_edge(1, 2, length=1000)
    return graph


@pytest.fixture
def auth_service():
    mock = MagicMock()
    mock.check_access_token.return_value = (Status.SUCCESS, None, None)
    return mock


@pytest.fixture
def service(empty_graph, auth_service):
    return RouteService(empty_graph, auth_service)


@pytest.fixture
def patched_nodes():
    """Patch nearest-node lookup so tests focus on routing/status behavior."""
    with patch("src.service.route.route_service.PathUtils") as MockPathUtils:
        MockPathUtils.return_value.find_nearest_node_with_expansion.return_value = 1
        yield MockPathUtils


@pytest.fixture(autouse=True)
def route_history_side_effects():
    with patch(
        "src.service.route.route_service.UserRepository.find_by_provider_and_provider_id",
        return_value=None,
    ):
        yield


class TestAuthFailure:
    def test_토큰이_만료되면_access_expired_token_status를_반환한다(self, service, auth_service):
        auth_service.check_access_token.return_value = (Status.ACCESS_EXPIRED_TOKEN, None, None)

        result = service.get_route(ACCESS_TOKEN, origin=ORIGIN, mode=WalkMode.CIRCULAR_RANDOM)

        assert result.status == WalkRouteStatus.ACCESS_EXPIRED_TOKEN

    def test_토큰이_유효하지_않으면_invalid_token_status를_반환한다(self, service, auth_service):
        auth_service.check_access_token.return_value = (Status.INVALID_TOKEN, None, None)

        result = service.get_route(ACCESS_TOKEN, origin=ORIGIN, mode=WalkMode.CIRCULAR_RANDOM)

        assert result.status == WalkRouteStatus.INVALID_TOKEN


class TestUnknownMode:
    def test_알_수_없는_모드는_예외를_발생시킨다(self, service):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            service.get_route(ACCESS_TOKEN, origin=ORIGIN, mode="invalid_mode")


class TestOnewayWithoutDestination:
    @pytest.mark.parametrize(
        "mode",
        [
            WalkMode.ONEWAY_SHORTEST,
            WalkMode.ONEWAY_RANDOM,
        ],
    )
    def test_편도_모드에_destination_없으면_invalid_destination을_반환한다(
        self, service, patched_nodes, mode
    ):
        result = service.get_route(ACCESS_TOKEN, origin=ORIGIN, mode=mode)

        assert result.status == WalkRouteStatus.INVALID_DESTINATION


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
        mock_engine_instance.run.return_value = SUCCESS_RESPONSE.model_copy(update={"mode": mode})
        MockEngineClass = MagicMock(return_value=mock_engine_instance)

        service.base_engines[mode] = MockEngineClass
        service.get_route(
            ACCESS_TOKEN,
            origin=ORIGIN,
            destination=destination,
            target_km=3.0,
            mode=mode,
        )

        MockEngineClass.assert_called_once()

    def test_엔진의_run_결과가_그대로_반환된다(self, service, patched_nodes):
        mock_engine_instance = MagicMock()
        mock_engine_instance.run.return_value = SUCCESS_RESPONSE
        MockEngineClass = MagicMock(return_value=mock_engine_instance)

        service.base_engines[WalkMode.CIRCULAR_RANDOM] = MockEngineClass
        result = service.get_route(
            ACCESS_TOKEN,
            origin=ORIGIN,
            target_km=3.0,
            mode=WalkMode.CIRCULAR_RANDOM,
        )

        assert result.status == WalkRouteStatus.SUCCESS
        assert result.total_km == 1.5

    def test_엔진이_실패_status를_반환하면_그대로_전달된다(self, service, patched_nodes):
        mock_engine_instance = MagicMock()
        mock_engine_instance.run.return_value = FAILED_RESPONSE
        MockEngineClass = MagicMock(return_value=mock_engine_instance)

        service.base_engines[WalkMode.CIRCULAR_RANDOM] = MockEngineClass
        result = service.get_route(
            ACCESS_TOKEN,
            origin=ORIGIN,
            target_km=3.0,
            mode=WalkMode.CIRCULAR_RANDOM,
        )

        assert result.status == WalkRouteStatus.NO_PATH
