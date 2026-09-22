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
    WalkRouteResponse,
    WalkRouteStatus,
)
from src.agent.nodes.route_executor import RouteExecutor
from src.repository.layer.route_poi_repository import RoutePoiRepository
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
            WalkMode.WAYPOINT,
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
            (WalkMode.WAYPOINT, DEST),
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

    def test_후보가_여러_개여도_최종_경로에만_POI와_이력_id가_붙는다(self, service, patched_nodes):
        mock_engine_instance = MagicMock()
        mock_engine_instance.run.return_value = [
            SUCCESS_RESPONSE.model_copy(update={"total_km": 1.5}),
            SUCCESS_RESPONSE.model_copy(update={"total_km": 1.6}),
        ]
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
        ) as find_pois, patch(
            "src.service.route.route_service.UserRepository.find_by_provider_and_provider_id",
            return_value=MagicMock(id=1),
        ), patch(
            "src.service.route.route_service.RouteHistoryRepository.save",
            return_value=MagicMock(id=99),
        ) as save_history:
            result = service.get_route(
                ACCESS_TOKEN,
                origin=ORIGIN,
                target_km=3.0,
                mode=WalkMode.CIRCULAR_RANDOM,
            )

        assert len(result) == 1
        assert find_pois.call_count == 1  # 최종 경로만 POI 조회
        assert result[0].nearby_pois[0].category == "toilet"
        assert save_history.call_count == 1
        assert result[0].id == 99

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


class TestOnewayRandomEngineWiring:
    """WalkMode.ONEWAY_RANDOM이 GRASP+ALNS 편도 엔진으로 배선됐는지 확인한다
    (2026-09-20, #498 확장 — 이전에는 OnewayAstarEngine 임시 배선이었다)."""

    def test_기본_엔진_클래스는_OnewayGraspWaypointAlnsEngine이다(self, service):
        from src.route_engine.engines.oneway_grasp_waypoint_alns import OnewayGraspWaypointAlnsEngine

        assert service.base_engines[WalkMode.ONEWAY_RANDOM] is OnewayGraspWaypointAlnsEngine

    def test_엔진_생성_시_custom_weights_대신_cost_context를_넘긴다(self, service, patched_nodes):
        """CIRCULAR_RANDOM 분기와 동일한 배선 — 가중 비용은 cost_context로만 전달한다."""
        mock_engine_instance = MagicMock()
        mock_engine_instance.run.return_value = [SUCCESS_RESPONSE.model_copy(update={"mode": WalkMode.ONEWAY_RANDOM})]
        MockEngineClass = MagicMock(return_value=mock_engine_instance)
        service.base_engines[WalkMode.ONEWAY_RANDOM] = MockEngineClass

        service.get_route(
            ACCESS_TOKEN,
            origin=ORIGIN,
            destination=DEST,
            target_km=3.0,
            mode=WalkMode.ONEWAY_RANDOM,
        )

        MockEngineClass.assert_called_once()
        _, kwargs = MockEngineClass.call_args
        assert "cost_context" in kwargs
        assert "custom_weights" not in kwargs


class TestWaypointRouting:
    """RouteService <-> WaypointComposerEngine 연동 검증."""

    def test_경유지의_nearest_node가_없으면_실패를_반환한다(self, service):
        with patch("src.service.route.route_service.PathUtils") as MockPathUtils:
            MockPathUtils.return_value.find_nearest_node_with_expansion.side_effect = [1, 1, None]
            result = service.get_route(
                ACCESS_TOKEN,
                origin=ORIGIN,
                destination=DEST,
                mode=WalkMode.WAYPOINT,
                waypoints=[Coordinate(lat=37.55, lon=127.05)],
            )

        assert result[0].status == WalkRouteStatus.NO_NEAREST_END_NODE

    def _capture_input(self, service):
        """base_engines[WAYPOINT]를 가짜 엔진으로 바꿔 실제로 구성된 WaypointRouteInput을 잡아낸다."""
        captured = {}

        # 이 테스트가 확인하는 것은 구성된 WaypointRouteInput뿐이다. 엔진 시그니처가
        # 늘어날 때마다 깨지지 않도록 나머지는 **kwargs로 받아 그대로 보관한다.
        def fake_engine(inp, G, **kwargs):
            captured["inp"] = inp
            captured.update(kwargs)
            mock_instance = MagicMock()
            mock_instance.run.return_value = [
                SUCCESS_RESPONSE.model_copy(update={"mode": WalkMode.WAYPOINT})
            ]
            return mock_instance

        service.base_engines[WalkMode.WAYPOINT] = fake_engine
        return captured

    def test_leg_modes_미지정시_전_구간이_최단경로로_패딩된다(self, service, patched_nodes):
        captured = self._capture_input(service)

        service.get_route(
            ACCESS_TOKEN,
            origin=ORIGIN,
            destination=DEST,
            mode=WalkMode.WAYPOINT,
            waypoints=[Coordinate(lat=37.55, lon=127.05), Coordinate(lat=37.57, lon=127.06)],
        )

        assert captured["inp"].leg_modes == ["oneway_shortest"] * 3
        assert captured["inp"].leg_target_km == [None, None, None]

    def test_leg_modes_일부만_지정하면_나머지만_최단경로로_패딩된다(self, service, patched_nodes):
        captured = self._capture_input(service)

        service.get_route(
            ACCESS_TOKEN,
            origin=ORIGIN,
            destination=DEST,
            mode=WalkMode.WAYPOINT,
            waypoints=[Coordinate(lat=37.55, lon=127.05)],
            leg_modes=["oneway_random"],
            leg_target_km=[1.2],
        )

        assert captured["inp"].leg_modes == ["oneway_random", "oneway_shortest"]
        assert captured["inp"].leg_target_km == [1.2, None]

    def test_경유지가_없으면_단일_구간으로_구성된다(self, service, patched_nodes):
        captured = self._capture_input(service)

        service.get_route(
            ACCESS_TOKEN,
            origin=ORIGIN,
            destination=DEST,
            mode=WalkMode.WAYPOINT,
        )

        assert captured["inp"].waypoints == []
        assert captured["inp"].leg_modes == ["oneway_shortest"]
        assert captured["inp"].leg_target_km == [None]


def _chat_state(feature_labels=None):
    origin = Location(lat=37.5, lon=127.0)
    return State(
        user_id=1,
        current_location=origin,
        access_token="token",
        mode=WalkMode.CIRCULAR_RANDOM,
        user_context=CircularPreference(origin=origin, target_km=2.0),
        feature_labels=feature_labels or {},
    )


class TestRouteWeightPersonalization:
    """
    2026-09-17: 테마 기반 자동 프로필 선택(_select_profile)이 제거되고 safety/comfort
    두 축만 개인화하는 방식으로 바뀐 뒤의 RouteExecutor 동작을 검증한다.
    """

    def test_설문_safety_comfort_delta만_반영되고_나머지_축은_스키마_기본값이다(self):
        preference = MagicMock(weights_safety=0.8, weights_comfort=0.9)

        with patch(
            "src.agent.nodes.route_executor.UserPreferenceRepository.get_by_user_id",
            return_value=preference,
        ):
            weights = RouteExecutor()._build_weights(_chat_state())

        assert weights.safety == pytest.approx(0.8)
        assert weights.comfort == pytest.approx(0.9)

    def test_설문값이_없으면_스키마_기본값을_사용한다(self):
        with patch(
            "src.agent.nodes.route_executor.UserPreferenceRepository.get_by_user_id",
            return_value=None,
        ):
            weights = RouteExecutor()._build_weights(_chat_state())

        assert weights.safety == pytest.approx(0.5)
        assert weights.comfort == pytest.approx(0.0)


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
