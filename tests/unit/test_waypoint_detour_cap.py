"""
tests/unit/test_waypoint_detour_cap.py
완성된 경유지 경로에 대한 우회 상한 — #445

상한은 leg가 아니라 **요청 전체**의 성질이다. leg마다 독립 적용하면 5구간 경로가
허용치를 leg 수만큼 넘길 수 있으므로, 모든 구간을 이어붙인 뒤 한 번만 판정한다.
비교는 반올림 전 거리(length 합)로 한다 — leg별 total_km는 이미 소수점 둘째 자리에서
반올림돼 leg마다 최대 5m씩 오차가 쌓인다.

검증 항목:
  - 상한 이내면 선호 경로를 쓰고 preference_applied=True
  - 정확히 경계면 초과가 아니다(> 이지 >= 가 아니다)
  - 상한 초과면 거리 기준 경로로 되돌리고 detour_cap_exceeded를 남긴다
  - 되돌린 경우 좌표·total_km도 거리 기준 경로의 값이어야 한다
  - 기준 경로를 만들지 못하면 선호 경로를 쓰되 baseline_failed로 남긴다
  - 경유지가 여러 개여도 구간별이 아니라 전체 경로로 비교한다
  - 사용자별 가중치가 그래프에 남지 않는다
"""

import math
from unittest.mock import MagicMock

import networkx as nx
import pytest

from src.interfaces.schema.walk_schema import WalkRouteStatus
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.engines.oneway_astar import OnewayAstarEngine
from src.route_engine.engines.waypoint import WaypointComposerEngine
from src.route_engine.scoring.detour_cap import apply_detour_cap, path_distance_m
from src.route_engine.scoring.weighted_edge_cost import WeightedEdgeCost
from src.schema.route_schema import (
    SafetyComfortPreference,
    WaypointCoordinate,
    WaypointRouteInput,
)
from src.route_engine.weighted_cost_runtime import (
    attach_weighted_cost,
    build_request_cost_context,
    prepare_weighted_cost,
)

K = 1.0
LAMBDA = 0.5

# ── 그래프 ──────────────────────────────────────────────────────────────────
#
#   S ── A ── B ── T      직선(짧지만 위험)
#   └─ C ── D ─┘          우회(길지만 안전)

S, A, B, T, C, D = 0, 1, 2, 3, 4, 5

_POS = {
    S: (37.5000, 127.0000),
    A: (37.5000, 127.0020),
    B: (37.5000, 127.0040),
    T: (37.5000, 127.0060),
    C: (37.5008, 127.0020),
    D: (37.5008, 127.0040),
}
_DIRECT = [S, A, B, T]
_DETOUR = [S, C, D, T]


def _haversine_m(a: int, b: int) -> float:
    (lat1, lon1), (lat2, lon2) = _POS[a], _POS[b]
    return PathUtils._haversine_m(lat1, lon1, lat2, lon2)


def make_graph() -> nx.Graph:
    """직선은 위험하고 우회는 안전한 그래프. 경사는 전 구간 동일(평탄)."""
    G = nx.Graph()
    for node, (lat, lon) in _POS.items():
        G.add_node(node, lat=lat, lon=lon, x=lon, y=lat)
    for path, (safety, accident) in ((_DIRECT, (0.0, 1.0)), (_DETOUR, (1.0, 0.0))):
        for u, v in zip(path, path[1:]):
            G.add_edge(
                u, v,
                length=_haversine_m(u, v),
                safety_score=safety, accident_score=accident, slope_score=1.0,
            )
    attach_weighted_cost(G, prepare_weighted_cost(G, enabled=True, coverage_min_ratio=0.95))
    return G


def make_context(G: nx.Graph, safety=0.9, comfort=0.0):
    return build_request_cost_context(
        G, safety_preference=safety, slope_preference=comfort,
        weight_limit=K, accident_ratio=LAMBDA,
    )


def make_engine(G, *, max_ratio: float, waypoints=(), context=...):
    """경유지 없이 S -> T 한 구간이 기본. waypoints를 주면 구간이 늘어난다."""
    stops = list(waypoints)
    legs = len(stops) + 1
    inp = WaypointRouteInput(
        start_lat=_POS[S][0], start_lon=_POS[S][1],
        end_lat=_POS[T][0], end_lon=_POS[T][1],
        waypoints=[WaypointCoordinate(lat=_POS[n][0], lon=_POS[n][1]) for n in stops],
        leg_modes=["oneway_preferred"] * legs,
        leg_target_km=[None] * legs,
    )
    return WaypointComposerEngine(
        inp, G,
        cost_context=make_context(G) if context is ... else context,
        detour_max_ratio=max_ratio,
    )


DIRECT_M = None   # make_graph() 이후 채워짐
DETOUR_M = None


@pytest.fixture
def graph():
    global DIRECT_M, DETOUR_M
    G = make_graph()
    DIRECT_M = path_distance_m(G, _DIRECT)
    DETOUR_M = path_distance_m(G, _DETOUR)
    return G


# ── 상한 이내 / 경계 / 초과 ─────────────────────────────────────────────────


def test_detour_within_cap_keeps_the_preferred_route(graph):
    response = make_engine(graph, max_ratio=1.0).run()[0]

    assert response.status == WalkRouteStatus.SUCCESS
    assert response.preference_applied is True
    assert response.preference_skipped_reason is None
    assert response.total_km == pytest.approx(round(DETOUR_M / 1000, 2))


def test_exactly_at_the_boundary_is_not_capped(graph):
    """경계값은 초과가 아니다 — 판정이 > 이지 >= 가 아님을 고정한다.

    비율을 그대로 쓰면 DETOUR_M > DIRECT_M * (1 + 비율)이 부동소수점 1 ulp 차이로
    참이 될 수 있어 우연에 기대게 된다. 표현 가능한 바로 다음 값을 써서 "경계 이상"이
    확실한 지점에서 판정한다.
    """
    exact = math.nextafter(DETOUR_M / DIRECT_M - 1.0, math.inf)

    response = make_engine(graph, max_ratio=exact).run()[0]

    assert response.preference_applied is True
    assert response.total_km == pytest.approx(round(DETOUR_M / 1000, 2))


def test_over_cap_falls_back_to_the_distance_route(graph):
    response = make_engine(graph, max_ratio=0.0).run()[0]

    assert response.status == WalkRouteStatus.SUCCESS
    assert response.preference_applied is False
    assert response.preference_skipped_reason == "detour_cap_exceeded"
    # 좌표·거리 모두 거리 기준 경로의 값이어야 한다
    assert response.total_km == pytest.approx(round(DIRECT_M / 1000, 2))
    assert len(response.coordinates) == len(_DIRECT)


def test_capped_route_coordinates_match_the_distance_route(graph):
    capped = make_engine(graph, max_ratio=0.0).run()[0]
    distance_only = make_engine(graph, max_ratio=0.0, context=None).run()[0]

    assert capped.coordinates == distance_only.coordinates


# ── 기준 경로 실패 ──────────────────────────────────────────────────────────


def test_baseline_failure_keeps_the_route_but_reports_it(graph, monkeypatch):
    """기준 경로를 못 만들면 상한을 검증했다고 표시하면 안 된다."""
    monkeypatch.setattr(
        WaypointComposerEngine, "_build_distance_baseline",
        lambda self, stops: None,
    )

    response = make_engine(graph, max_ratio=0.0).run()[0]

    assert response.status == WalkRouteStatus.SUCCESS
    assert response.preference_applied is True          # 경로 자체는 살린다
    assert response.preference_skipped_reason == "baseline_failed"
    assert response.total_km == pytest.approx(round(DETOUR_M / 1000, 2))


def test_apply_detour_cap_marks_missing_baseline_unverified(graph):
    decision = apply_detour_cap(graph, _DETOUR, None, max_ratio=0.0)

    assert decision.verified is False
    assert decision.capped is False
    assert decision.path == _DETOUR


def test_apply_detour_cap_verifies_when_both_paths_exist(graph):
    decision = apply_detour_cap(graph, _DETOUR, _DIRECT, max_ratio=1.0)

    assert decision.verified is True
    assert decision.capped is False


# ── 여러 경유지 ─────────────────────────────────────────────────────────────


def test_multiple_waypoints_are_compared_as_one_whole_route(graph):
    """구간마다 따로 재면 허용치를 구간 수만큼 넘길 수 있다."""
    engine = make_engine(graph, max_ratio=1.0, waypoints=[D])
    response = engine.run()[0]

    assert response.status == WalkRouteStatus.SUCCESS
    assert response.preference_applied is True


def test_multiple_waypoints_are_preserved_when_capped(graph):
    engine = make_engine(graph, max_ratio=0.0, waypoints=[D])
    response = engine.run()[0]

    assert response.status == WalkRouteStatus.SUCCESS
    # 상한을 넘겨 되돌려도 경유지는 여전히 경로 위에 있어야 한다
    wp_coord = [_POS[D][0], _POS[D][1]]
    assert any(
        math.isclose(c[0], wp_coord[0], abs_tol=1e-6)
        and math.isclose(c[1], wp_coord[1], abs_tol=1e-6)
        for c in response.coordinates
    )


# ── 선호 없음 / 요청 격리 ───────────────────────────────────────────────────


def test_without_context_no_cap_is_applied(graph):
    """가중 연결을 안 쓴 요청은 기준 경로를 만들지도, 상한을 재지도 않는다."""
    response = make_engine(graph, max_ratio=0.0, context=None).run()[0]

    assert response.preference_applied is False
    assert response.total_km == pytest.approx(round(DIRECT_M / 1000, 2))


def test_different_preferences_do_not_leak_between_requests(graph):
    """사용자별 가중치가 그래프에 남으면 다음 요청과 섞인다."""
    first = make_context(graph, safety=0.9, comfort=0.0)
    second = make_context(graph, safety=0.0, comfort=0.9)

    make_engine(graph, max_ratio=1.0, context=first).run()
    make_engine(graph, max_ratio=1.0, context=second).run()

    assert first is not second
    assert first.alpha != second.alpha
    assert not any(isinstance(v, WeightedEdgeCost) for v in graph.graph.values())


def test_preference_signal_axes_are_independent():
    """안전만 지정했다면 편안함은 비활성으로 남는다."""
    only_safety = SafetyComfortPreference(safety=0.8)

    assert only_safety.is_active is True
    assert only_safety.as_coefficients() == (0.8, 0.0)
    assert SafetyComfortPreference().is_active is False


# ── 부분 경로 ───────────────────────────────────────────────────────────────


def test_partial_route_does_not_claim_preference(graph, monkeypatch):
    """일부 구간이 실패하면 비교할 전체 기준 경로가 없어 상한을 적용할 수 없다.
    선호가 반영됐다고 보고하지 않고 사유를 남겨야 한다."""
    from src.interfaces.schema.walk_schema import WalkMode, WalkRouteResponse

    failed = WalkRouteResponse(
        status=WalkRouteStatus.NO_PATH, mode=WalkMode.WAYPOINT, coordinates=[], total_km=0.0,
    )

    def _fail(self):
        self.last_path_nodes = []
        self.last_path_nodes_by_candidate = [[]]
        return [failed]

    monkeypatch.setattr(OnewayAstarEngine, "run", _fail)

    response = make_engine(graph, max_ratio=1.0).run()[0]

    assert response.preference_applied is False
    assert response.preference_skipped_reason == "partial_route"


# ── RouteService 전 구간 통합 ───────────────────────────────────────────────


def _route_service(G):
    from src.interfaces.schema.auth_schema import Status
    from src.service.route.route_service import RouteService

    auth = MagicMock()
    auth.check_access_token.return_value = (Status.SUCCESS, None, None)
    return RouteService(G=G, auth_service=auth)


def _get_route(service, preference):
    from src.interfaces.schema.walk_schema import Coordinate, WalkMode

    return service.get_route(
        "token",
        origin=Coordinate(lat=_POS[S][0], lon=_POS[S][1]),
        destination=Coordinate(lat=_POS[T][0], lon=_POS[T][1]),
        mode=WalkMode.WAYPOINT,
        preference=preference,
    )[0]


def test_route_service_applies_an_active_preference_end_to_end(graph):
    """RouteService -> WaypointComposerEngine -> A* 전 구간에서 안전 선호가 반영된다."""
    response = _get_route(_route_service(graph), SafetyComfortPreference(safety=0.9))

    assert response.status == WalkRouteStatus.SUCCESS
    assert response.preference_applied is True
    assert response.total_km == pytest.approx(round(DETOUR_M / 1000, 2))


def test_route_service_without_preference_stays_on_distance(graph):
    response = _get_route(_route_service(graph), None)

    assert response.status == WalkRouteStatus.SUCCESS
    assert response.preference_applied is False
    assert response.preference_skipped_reason == "no_preference"
    assert response.total_km == pytest.approx(round(DIRECT_M / 1000, 2))
