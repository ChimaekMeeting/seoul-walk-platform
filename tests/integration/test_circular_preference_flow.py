"""#471: 계산된 선호가 실제 순환 엔진의 비용과 완성 후보까지 전달되는지 검증한다.

DB·인증·StructuredTool 바인딩만 대체하고 Executor, Tool, Service, GRASP+ALNS는
실제 코드를 실행한다. 발화에서 라벨을 추출하는 LLM 검증은 #463의 범위다.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import networkx as nx
import pytest

from src.agent.nodes.route_executor import MODE_TOOL_MAP, RouteExecutor
from src.agent.tools.route_tools import RouteTool
from src.config.settings import settings
from src.interfaces.schema.auth_schema import Status
from src.interfaces.schema.walk_schema import Coordinate, WalkMode, WalkRouteStatus
from src.route_engine.engines.circular_grasp_waypoint_alns import CircularGraspWaypointAlnsEngine
from src.route_engine.weighted_cost_runtime import attach_weighted_cost, prepare_weighted_cost
from src.schema.prewalk_schema import CircularPreference, FeatureLabel, FeatureTag, Location, State
from src.schema.route_schema import GpsArtPoint, Weights
from src.service.route.route_service import RouteService


class _DirectInvoke:
    """공통 conftest가 대체한 StructuredTool의 ainvoke 인터페이스만 복원한다."""

    def __init__(self, coroutine):
        self.coroutine = coroutine

    async def ainvoke(self, args):
        return await self.coroutine(**args)


def _executor(service):
    tool = RouteTool.__new__(RouteTool)
    tool.route_service = service
    tool.tool_map = {
        name: _DirectInvoke(getattr(tool, name)) for name in MODE_TOOL_MAP.values()
    }
    executor = RouteExecutor.__new__(RouteExecutor)
    executor.route_tool = tool
    return executor


def _state(origin, *, labels=None, target_km=1.4):
    return State(
        user_id=1,
        current_location=origin,
        access_token="test-circular-token",
        mode=WalkMode.CIRCULAR_RANDOM,
        user_context=CircularPreference(origin=origin, target_km=target_km),
        feature_labels=labels or {},
    )


@pytest.fixture
def graph():
    graph = nx.convert_node_labels_to_integers(nx.grid_2d_graph(7, 7))
    for node in graph:
        row, col = divmod(node, 7)
        graph.nodes[node].update(lat=37.57 + row * 0.0005, lon=126.98 + col * 0.0005)
    for u, v, edge in graph.edges(data=True):
        # 각 edge는 좌표 사이 직선거리보다 길다(Haversine 하한 유지).
        edge.update(
            length=80.0,
            link_id=f"{u}-{v}",
            safety_score=0.2 + 0.1 * (u % 5),
            accident_score=0.1,
            slope_score=0.3 + 0.1 * (v % 5),
        )
    return graph


@pytest.fixture
def flow(monkeypatch, graph):
    from src.agent.nodes import route_executor as executor_module
    from src.service.route import route_service as service_module

    monkeypatch.setattr(settings, "WALK_WEIGHT_LIMIT", 0.5)
    monkeypatch.setattr(settings, "WALK_UNSAFE_ACCIDENT_RATIO", 0.5)
    preference = SimpleNamespace(weights_safety=0.2, weights_comfort=0.4)
    monkeypatch.setattr(
        executor_module.UserPreferenceRepository, "get_by_user_id", lambda _: preference,
    )
    monkeypatch.setattr(
        service_module.UserRepository, "find_by_provider_and_provider_id", lambda *_: None,
    )
    monkeypatch.setattr(service_module.RoutePoiRepository, "find_near_route", lambda _: [])
    auth = MagicMock()
    auth.check_access_token.return_value = (Status.SUCCESS, "test", "test")
    service = RouteService(graph, auth)
    engines = []

    def capture_engine(*args, **kwargs):
        engine = CircularGraspWaypointAlnsEngine(*args, **kwargs)
        engines.append(engine)
        return engine

    service.base_engines[WalkMode.CIRCULAR_RANDOM] = capture_engine
    return SimpleNamespace(
        service=service, executor=_executor(service), engines=engines,
        preference=preference, origin=Location(**graph.nodes[24]),
    )


def _prepare(graph, *, enabled=True):
    report = prepare_weighted_cost(graph, enabled=enabled, coverage_min_ratio=0.95)
    attach_weighted_cost(graph, report)
    return report


def _run(flow, *, labels=None):
    result = asyncio.run(flow.executor.run(_state(flow.origin, labels=labels)))
    assert result.route_result is not None
    assert result.route_result[0].status == WalkRouteStatus.SUCCESS
    return flow.engines[-1]


@pytest.mark.parametrize("feature", [FeatureTag.SAFETY, FeatureTag.COMFORT])
def test_blended_preference_reaches_real_circular_engine_and_candidates(flow, graph, feature):
    assert _prepare(graph).ok
    labels = {feature: FeatureLabel(preference_label="high", explicitness_label="explicit_soft")}
    engine = _run(flow, labels=labels)

    # 설문 (0.2, 0.4)에 대화 요구를 70% 반영한 최종값. 계산기를 재호출하지 않고
    # 기대값을 고정해 기본 설문만 전달하거나 두 축을 바꾸는 회귀도 잡는다.
    safety, comfort = (0.585, 0.4) if feature == FeatureTag.SAFETY else (0.2, 0.645)
    context = engine.cost_context
    assert context is not None
    assert context.enabled
    assert (context.alpha, context.beta) == pytest.approx(
        (0.5 * safety / (safety + comfort), 0.5 * comfort / (safety + comfort))
    )
    assert engine.cost_cache.cost_context is context
    assert engine.last_route is not None
    for route in [engine.last_route, *engine.last_alternative_routes]:
        expected_cost = sum(
            context.weight(u, v, graph[u][v])
            for u, v in zip(route.node_ids, route.node_ids[1:])
        )
        assert route.weighted_cost_m == pytest.approx(expected_cost)
        assert route.weighted_cost_m > route.distance_m


@pytest.mark.parametrize("reason", ["zero_weights", "missing_scores", "disabled"])
def test_distance_fallback_survives_the_full_circular_flow(flow, graph, reason):
    if reason == "zero_weights":
        flow.preference.weights_safety = flow.preference.weights_comfort = 0.0
    elif reason == "missing_scores":
        for _, _, edge in graph.edges(data=True):
            edge.pop("accident_score")
    _prepare(graph, enabled=reason != "disabled")

    engine = _run(flow)

    assert engine.cost_context is None
    for route in [engine.last_route, *engine.last_alternative_routes]:
        assert route.weighted_cost_m == pytest.approx(route.distance_m)


@pytest.mark.parametrize("mode", [WalkMode.ONEWAY_SHORTEST, WalkMode.GPS_ART])
def test_other_distance_modes_do_not_forward_preference(flow, graph, mode):
    assert _prepare(graph).ok
    tool = flow.executor.route_tool
    origin = Coordinate(lat=flow.origin.lat, lon=flow.origin.lon)
    weights = Weights(safety=0.9, comfort=0.8)
    if mode == WalkMode.GPS_ART:
        tool.gps_art_service = SimpleNamespace(get_shape_points=AsyncMock(return_value=[
            GpsArtPoint(x=0, y=0), GpsArtPoint(x=1, y=0),
            GpsArtPoint(x=1, y=1), GpsArtPoint(x=0, y=0),
        ]))
        call = tool.gps_art_route(origin, "test-triangle", target_km=0.8, custom_weights=weights)
    else:
        call = tool.oneway_shortest_route(origin, Coordinate(**graph.nodes[0]), custom_weights=weights)

    with patch.object(flow.service, "_build_cost_context", wraps=flow.service._build_cost_context) as build_cost:
        routes = asyncio.run(call)

    assert routes[0].status == WalkRouteStatus.SUCCESS
    assert routes[0].mode == mode
    build_cost.assert_called_once_with(None)
