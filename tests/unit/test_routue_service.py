"""
tests/unit/test_routue_service.py
RouteService unit tests for the three supported walk modes.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import networkx as nx
import pytest

from src.interfaces.schema.auth_schema import Status
from src.interfaces.schema.walk_schema import (
    Coordinate,
    WalkMode,
    WalkRouteRequest,
    WalkRouteResponse,
    WalkRouteStatus,
)
from src.agent.nodes.route_executor import RouteExecutor
from src.repository.layer.route_poi_repository import RoutePoiRepository
from src.route_engine.profiles import ScoringProfile
from src.schema.prewalk_schema import CircularPreference, Location, State
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

        assert result[0].status == WalkRouteStatus.ACCESS_EXPIRED_TOKEN

    def test_토큰이_유효하지_않으면_invalid_token_status를_반환한다(self, service, auth_service):
        auth_service.check_access_token.return_value = (Status.INVALID_TOKEN, None, None)

        result = service.get_route(ACCESS_TOKEN, origin=ORIGIN, mode=WalkMode.CIRCULAR_RANDOM)

        assert result[0].status == WalkRouteStatus.INVALID_TOKEN


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

        assert result[0].status == WalkRouteStatus.INVALID_DESTINATION


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
        mock_engine_instance.run.return_value = [SUCCESS_RESPONSE.model_copy(update={"mode": mode})]
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
        mock_engine_instance.run.return_value = [SUCCESS_RESPONSE]
        MockEngineClass = MagicMock(return_value=mock_engine_instance)

        service.base_engines[WalkMode.CIRCULAR_RANDOM] = MockEngineClass
        result = service.get_route(
            ACCESS_TOKEN,
            origin=ORIGIN,
            target_km=3.0,
            mode=WalkMode.CIRCULAR_RANDOM,
        )

        assert result[0].status == WalkRouteStatus.SUCCESS
        assert result[0].total_km == 1.5

    def test_성공_경로에는_주변_POI를_붙인다(self, service, patched_nodes):
        mock_engine_instance = MagicMock()
        mock_engine_instance.run.return_value = [SUCCESS_RESPONSE.model_copy()]
        service.base_engines[WalkMode.CIRCULAR_RANDOM] = MagicMock(
            return_value=mock_engine_instance
        )
        pois = [{
            "category": "toilet",
            "name": "개방화장실",
            "address": "서울",
            "lat": 37.5,
            "lon": 127.0,
            "distance_to_route_m": 12.3,
        }]

        with patch(
            "src.service.route.route_service.RoutePoiRepository.find_near_route",
            return_value=pois,
        ) as find_pois:
            result = service.get_route(
                ACCESS_TOKEN,
                origin=ORIGIN,
                target_km=3.0,
                mode=WalkMode.CIRCULAR_RANDOM,
            )

        find_pois.assert_called_once_with(SUCCESS_RESPONSE.coordinates)
        assert result[0].nearby_pois[0].category == "toilet"

    def test_엔진이_실패_status를_반환하면_그대로_전달된다(self, service, patched_nodes):
        mock_engine_instance = MagicMock()
        mock_engine_instance.run.return_value = [FAILED_RESPONSE]
        MockEngineClass = MagicMock(return_value=mock_engine_instance)

        service.base_engines[WalkMode.CIRCULAR_RANDOM] = MockEngineClass
        result = service.get_route(
            ACCESS_TOKEN,
            origin=ORIGIN,
            target_km=3.0,
            mode=WalkMode.CIRCULAR_RANDOM,
        )

        assert result[0].status == WalkRouteStatus.NO_PATH


def _chat_state(themes=None, profile=None):
    origin = Location(lat=37.5, lon=127.0)
    return State(
        user_id=1,
        current_location=origin,
        access_token="token",
        mode=WalkMode.CIRCULAR_RANDOM,
        user_context=CircularPreference(origin=origin, target_km=2.0),
        themes=themes or [],
        profile=profile,
    )


class TestRouteProfilePropagation:
    def test_계단이_불편한_테마는_accessible_프로필을_선택한다(self):
        assert (
            RouteExecutor._select_profile(_chat_state(["계단이 불편한"]))
            == ScoringProfile.ACCESSIBLE
        )

    def test_활기찬_테마는_convenient_프로필을_선택한다(self):
        assert (
            RouteExecutor._select_profile(_chat_state(["활기찬"]))
            == ScoringProfile.CONVENIENT
        )

    def test_명시한_프로필이_테마보다_우선한다(self):
        state = _chat_state(["계단이 불편한"], ScoringProfile.NATURE)
        assert RouteExecutor._select_profile(state) == ScoringProfile.NATURE

    def test_접근성_프로필과_설문_delta를_함께_반영한다(self):
        preference = MagicMock()
        for key in (
            "safety",
            "nature",
            "slope",
            "running",
            "landmark",
            "child",
            "convenience",
            "accessibility",
        ):
            setattr(preference, f"weights_{key}", None)
        preference.weights_nature = 0.2

        with patch(
            "src.agent.nodes.route_executor.UserPreferenceRepository.get_by_user_id",
            return_value=preference,
        ):
            weights = RouteExecutor()._build_weights(
                _chat_state(),
                ScoringProfile.ACCESSIBLE,
            )

        assert weights.accessibility == pytest.approx(0.8)
        assert weights.nature == pytest.approx(0.6)

    def test_run이_선택한_프로필을_route_tool에_전달한다(self):
        executor = RouteExecutor.__new__(RouteExecutor)
        route_call = AsyncMock(return_value=None)
        executor.route_tool = MagicMock(
            tool_map={"circular_random_route": MagicMock(ainvoke=route_call)}
        )
        state = _chat_state(["계단이 불편한"])

        with patch(
            "src.agent.nodes.route_executor.UserPreferenceRepository.get_by_user_id",
            return_value=None,
        ):
            result = asyncio.run(executor.run(state))

        assert result.profile == ScoringProfile.ACCESSIBLE
        assert route_call.await_args.args[0]["profile"] == ScoringProfile.ACCESSIBLE


class TestRoutePoiLookup:
    def test_geography_거리_조인용_공간_인덱스를_생성한다(self):
        connection = MagicMock()
        context = MagicMock()
        context.__enter__.return_value = connection

        with patch(
            "src.repository.layer.route_poi_repository.engine.begin",
            return_value=context,
        ):
            RoutePoiRepository.create_spatial_index()

        statements = [
            str(call.args[0])
            for call in connection.execute.call_args_list
        ]
        assert any("idx_route_pois_geog" in sql for sql in statements)
        assert any("idx_walk_edges_geog" in sql for sql in statements)
        assert any("idx_walk_nodes_geog" in sql for sql in statements)

    def test_좌표가_둘_미만이면_POI를_조회하지_않는다(self):
        assert RoutePoiRepository.find_near_route([[37.5, 127.0]]) == []

    def test_경로_주변_POI를_응답_형태로_변환한다(self):
        row = {
            "category": "accessibility",
            "name": "엘리베이터",
            "address": "서울",
            "lat": 37.5,
            "lon": 127.0,
            "distance_to_route_m": 7.84,
        }
        result_proxy = MagicMock()
        result_proxy.mappings.return_value.all.return_value = [row]
        db = MagicMock()
        db.execute.return_value = result_proxy
        context = MagicMock()
        context.__enter__.return_value = db

        with patch(
            "src.repository.layer.route_poi_repository.get_postgresql_db",
            return_value=context,
        ):
            result = RoutePoiRepository.find_near_route(
                [[37.5, 127.0], [37.51, 127.01]]
            )

        assert result[0]["distance_to_route_m"] == 7.8
        params = db.execute.call_args.args[1]
        assert params["route_wkt"] == "LINESTRING(127.0 37.5, 127.01 37.51)"


class TestWalkProfileSchema:
    @pytest.mark.parametrize("profile", ["accessible", "convenient"])
    def test_직접_API가_새_프로필을_허용한다(self, profile):
        request = WalkRouteRequest.model_validate({
            "origin": {"lat": 37.5, "lon": 127.0},
            "target_km": 2.0,
            "mode": "circular_random",
            "profile": profile,
        })

        assert request.profile == ScoringProfile(profile)
