"""#498 확장: WalkMode.ONEWAY_RANDOM이 실제로 GRASP+ALNS 편도 우회 경로를 만드는지,
route_service.get_route() 진입점부터 mock 없이(DB/인증만 대체) 확인한다.

circular_preference_flow.py와 같은 관례(합성 격자 그래프 + 실제 RouteService/엔진)를
따른다 — 실제 서울 그래프(artifacts/walk_graph_v1.pkl, 160k+ 노드)는 무겁고
재현성 확인에는 굳이 필요하지 않다.
"""

from unittest.mock import MagicMock

import networkx as nx
import pytest

from src.interfaces.schema.auth_schema import Status
from src.interfaces.schema.walk_schema import Coordinate, WalkMode, WalkRouteStatus
from src.service.route.route_service import RouteService


@pytest.fixture
def graph():
    """7x7 격자 + 실제 위경도 간격. oneway_shortest(A*)와 oneway_random(GRASP+ALNS)의
    결과가 서로 다른 경로를 낼 수 있을 만큼 목적지까지 우회할 여지가 있어야 한다."""
    graph = nx.convert_node_labels_to_integers(nx.grid_2d_graph(7, 7))
    for node in graph:
        row, col = divmod(node, 7)
        graph.nodes[node].update(lat=37.5700 + row * 0.0015, lon=126.9800 + col * 0.0018)
    for u, v in graph.edges():
        lat1, lon1 = graph.nodes[u]["lat"], graph.nodes[u]["lon"]
        lat2, lon2 = graph.nodes[v]["lat"], graph.nodes[v]["lon"]
        from src.route_engine.engines.path_utils import PathUtils
        graph.edges[u, v]["length"] = PathUtils._haversine_m(lat1, lon1, lat2, lon2)
    return graph


@pytest.fixture
def service(graph, monkeypatch):
    from src.service.route import route_service as service_module

    monkeypatch.setattr(
        service_module.UserRepository, "find_by_provider_and_provider_id", lambda *_: None,
    )
    monkeypatch.setattr(service_module.RoutePoiRepository, "find_near_route", lambda _: [])
    auth = MagicMock()
    auth.check_access_token.return_value = (Status.SUCCESS, "test", "test")
    return RouteService(graph, auth)


def _corner(graph, row, col):
    return Coordinate(lat=graph.nodes[row * 7 + col]["lat"], lon=graph.nodes[row * 7 + col]["lon"])


def test_oneway_random_reaches_destination_and_reports_grasp_alns_mode(service, graph):
    origin = _corner(graph, 0, 0)
    destination = _corner(graph, 6, 6)

    results = service.get_route(
        access_token="test-token", origin=origin, destination=destination,
        target_km=1.5, mode=WalkMode.ONEWAY_RANDOM,
    )

    assert results[0].status == WalkRouteStatus.SUCCESS
    assert results[0].mode == WalkMode.ONEWAY_RANDOM
    assert results[0].coordinates[0] == pytest.approx([origin.lat, origin.lon], abs=1e-6)
    assert results[0].coordinates[-1] == pytest.approx([destination.lat, destination.lon], abs=1e-6)


def test_oneway_random_can_differ_from_oneway_shortest(service, graph):
    """target_km이 직선 최단거리보다 충분히 크면 GRASP+ALNS가 경유지를 골라 실제로
    A* 최단경로(oneway_shortest)보다 긴 우회 경로를 만들어야 한다 — 그렇지 않으면
    "우회" 로직이 이름만 있고 실제로는 여전히 최단경로와 동일하다는 뜻이다."""
    origin = _corner(graph, 0, 0)
    destination = _corner(graph, 6, 6)

    shortest = service.get_route(
        access_token="test-token", origin=origin, destination=destination,
        target_km=None, mode=WalkMode.ONEWAY_SHORTEST,
    )
    detour = service.get_route(
        access_token="test-token", origin=origin, destination=destination,
        target_km=2.5, mode=WalkMode.ONEWAY_RANDOM,
    )

    assert shortest[0].status == WalkRouteStatus.SUCCESS
    assert detour[0].status == WalkRouteStatus.SUCCESS
    assert detour[0].total_km > shortest[0].total_km
