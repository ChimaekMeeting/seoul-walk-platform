"""
tests/unit/test_weighted_cost_runtime.py
가중 비용의 기동 준비·요청별 생성과 RouteService 배선 — #445 6단계

핵심은 두 가지다.
  1. 그래프를 훑는 O(E) 커버리지 검사는 기동 때 1회만 돈다(실측 약 0.30초).
     요청은 붙어 있는 적재율·중앙값만 읽는다.
  2. 사용자별 alpha/beta는 그래프에 붙지 않는다. 요청 범위를 벗어나 공유되면
     다른 사용자의 가중치가 섞인다.

검증 항목:
  - WALK_WEIGHTED_COST_ENABLED=false면 준비를 건너뛴다
  - 커버리지 미달이면 report.ok=False로 붙고 요청 context는 만들어지지 않는다
  - 준비 실패(예외)해도 기동을 막지 않고 거리 전용으로 폴백한다
  - attach(None)은 이전 상태를 지운다
  - build_request_cost_context는 그래프를 다시 훑지 않는다
  - 선호도가 0이면 context를 만들지 않는다(거리 전용과 동일하므로)
  - 선호도 합이 상한을 넘으면 비례 축소된 alpha/beta가 들어간다
  - 커버리지가 계산한 중앙값이 요청 context로 전달된다
  - RouteService는 oneway_shortest에 context를 넘기지 않는다(설계 결정 A)
  - RouteService는 요청당 context를 하나만 만들어 모든 leg가 공유한다
  - WaypointComposerEngine은 OnewayAstarEngine leg에만 context를 넘긴다
"""

from unittest.mock import MagicMock

import networkx as nx
import pytest

from src.interfaces.schema.walk_schema import WalkMode
from src.route_engine.engines.oneway_astar import OnewayAstarEngine
from src.route_engine.engines.waypoint import WaypointComposerEngine
from src.route_engine.scoring.scoring_engine import (
    ACCIDENT_ATTR,
    SAFETY_ATTR,
    SLOPE_ATTR,
    WeightedEdgeCost,
)
from src.route_engine.weighted_cost_runtime import (
    COVERAGE_KEY,
    attach_weighted_cost,
    build_request_cost_context,
    get_coverage_report,
    prepare_weighted_cost,
)
from src.schema.route_schema import Weights, WaypointRouteInput
from src.schema.route_schema import WaypointCoordinate

K = 0.5
LAMBDA = 0.5

# ── 그래프 헬퍼 ─────────────────────────────────────────────────────────────


def scored_graph(n_edges: int = 10, missing: int = 0, safety=0.4) -> nx.Graph:
    """앞쪽 missing개 엣지만 safety_score가 None인 그래프."""
    G = nx.Graph()
    for i in range(n_edges):
        data = {
            "length": 10.0 + i,
            SAFETY_ATTR: safety,
            ACCIDENT_ATTR: 0.2,
            SLOPE_ATTR: 0.6,
        }
        if i < missing:
            data[SAFETY_ATTR] = None
        G.add_edge(i, i + 1, **data)
    return G


def bare_graph() -> nx.Graph:
    """현재 운영 artifact처럼 점수가 하나도 없는 그래프."""
    G = nx.Graph()
    G.add_edge(0, 1, length=100.0)
    G.add_edge(1, 2, length=50.0)
    return G


def prepared(G: nx.Graph, min_ratio: float = 0.9) -> nx.Graph:
    attach_weighted_cost(G, prepare_weighted_cost(G, enabled=True, coverage_min_ratio=min_ratio))
    return G


def request_context(G: nx.Graph, safety=0.5, slope=0.5):
    return build_request_cost_context(
        G,
        safety_preference=safety, slope_preference=slope,
        weight_limit=K, accident_ratio=LAMBDA,
    )


# ── 기동 준비 ───────────────────────────────────────────────────────────────


def test_disabled_setting_skips_preparation():
    assert prepare_weighted_cost(scored_graph(), enabled=False, coverage_min_ratio=0.9) is None


def test_prepared_report_is_attached_and_readable():
    G = prepared(scored_graph())

    report = get_coverage_report(G)
    assert report is not None and report.ok is True
    assert report.ratios[SAFETY_ATTR] == pytest.approx(1.0)


def test_coverage_shortfall_is_attached_with_ok_false():
    """왜 꺼졌는지 진단할 수 있어야 하므로 미달이어도 report 자체는 남긴다."""
    G = prepared(scored_graph(10, missing=5))

    report = get_coverage_report(G)
    assert report is not None
    assert report.ok is False
    assert report.missing_attrs() == [SAFETY_ATTR]


def test_bare_graph_disables_weighted_mode(caplog):
    """점수가 하나도 없는 현재 artifact 상태에서는 거리 전용으로 내려간다."""
    import logging

    with caplog.at_level(logging.WARNING):
        G = prepared(bare_graph())

    assert get_coverage_report(G).ok is False
    assert request_context(G) is None
    assert any("커버리지" in r.message for r in caplog.records)


def test_preparation_failure_does_not_block_startup(caplog, monkeypatch):
    import logging

    monkeypatch.setattr(
        WeightedEdgeCost, "check_coverage",
        classmethod(lambda cls, G, min_ratio: (_ for _ in ()).throw(RuntimeError("boom"))),
    )

    with caplog.at_level(logging.WARNING):
        result = prepare_weighted_cost(scored_graph(), enabled=True, coverage_min_ratio=0.9)

    assert result is None
    assert any("거리 전용으로 폴백" in r.message for r in caplog.records)


def test_attaching_none_clears_previous_state():
    G = prepared(scored_graph())
    assert COVERAGE_KEY in G.graph

    attach_weighted_cost(G, None)

    assert COVERAGE_KEY not in G.graph
    assert get_coverage_report(G) is None


# ── 요청별 생성 ─────────────────────────────────────────────────────────────


def test_request_context_does_not_rescan_the_graph(monkeypatch):
    """요청마다 O(E) 순회가 되살아나면 안 된다."""
    G = prepared(scored_graph())

    def _boom(*args, **kwargs):
        raise AssertionError("요청 경로에서 커버리지를 다시 재면 안 된다")

    monkeypatch.setattr(WeightedEdgeCost, "check_coverage", classmethod(_boom))

    assert request_context(G) is not None


def test_unprepared_graph_yields_no_context():
    assert request_context(scored_graph()) is None


def test_zero_preferences_yield_no_context():
    """비용이 정확히 length와 같아지므로 거리 전용과 구분할 이유가 없다."""
    G = prepared(scored_graph())

    assert request_context(G, safety=0.0, slope=0.0) is None


def test_preferences_over_limit_are_scaled_into_the_context():
    G = prepared(scored_graph())

    context = request_context(G, safety=0.5, slope=0.5)  # 합 1.0 > 상한 0.5

    assert context.alpha + context.beta == pytest.approx(K)
    assert context.alpha == pytest.approx(context.beta)


def test_medians_from_startup_reach_the_request_context():
    G = prepared(scored_graph(10, missing=1, safety=0.4))

    context = request_context(G)

    assert context.enabled is True
    assert context.medians[SAFETY_ATTR] == pytest.approx(0.4)
    # NULL 엣지도 중앙값으로 대체돼 탐색이 진행된다
    context.weight(0, 1, G[0][1])
    assert context.median_substitutions == 1


def test_context_is_not_stored_on_the_graph():
    """사용자별 가중치가 그래프에 남으면 다음 요청과 섞인다."""
    G = prepared(scored_graph())

    request_context(G, safety=0.9, slope=0.1)

    assert not any(isinstance(v, WeightedEdgeCost) for v in G.graph.values())


# ── RouteService 배선 ───────────────────────────────────────────────────────


@pytest.fixture
def service():
    from src.service.route.route_service import RouteService

    return RouteService(G=prepared(scored_graph()), auth_service=MagicMock())


ACTIVE = Weights(safety=0.8, comfort=0.2)


def test_build_cost_context_does_not_know_about_mode(service):
    """_build_cost_context는 이제 mode를 받지 않는다 — preference만 본다.
    설계 결정 A(oneway_shortest는 물리 최단 유지)는 _build_engine()의 모드별
    분기가 cost_context를 안 넘기는 방식으로 지킨다(여기서는 검증하지 않음)."""
    assert service._build_cost_context(ACTIVE) is not None
    assert service._build_cost_context(None) is None


def test_waypoint_mode_with_active_preference_gets_a_cost_context(service):
    context = service._build_cost_context(ACTIVE)

    assert context is not None
    assert context.enabled is True


def test_no_preference_keeps_waypoint_on_distance(service):
    assert service._build_cost_context(None) is None


def test_unspecified_axis_contributes_zero(service):
    """안전만 말했다면 편안함은 Weights.comfort 기본값(0.0)이 그대로 들어가야 한다."""
    context = service._build_cost_context(Weights(safety=0.8))

    assert context.alpha > 0
    assert context.beta == 0.0


# ── leg 방식 결정 (패딩 전) ─────────────────────────────────────────────────


def test_unspecified_legs_become_preferred_when_preference_is_active(service):
    context = service._build_cost_context(ACTIVE)

    assert service._resolve_fill_leg_mode([], ACTIVE, context) == ("oneway_preferred", None)


def test_unspecified_legs_stay_shortest_without_preference(service):
    assert service._resolve_fill_leg_mode([], None, None) == ("oneway_shortest", "no_preference")


def test_beam_leg_excludes_the_whole_request(service):
    """oneway_random이 섞이면 가중 연결 대상에서 빼되 사유를 남긴다."""
    context = service._build_cost_context(ACTIVE)

    assert service._resolve_fill_leg_mode(
        ["oneway_random"], ACTIVE, context,
    ) == ("oneway_shortest", "beam_leg_present")


def test_missing_scores_are_reported_as_such(service):
    """선호는 있는데 그래프 점수가 없어 가중 모드가 꺼진 경우."""
    assert service._resolve_fill_leg_mode([], ACTIVE, None) == (
        "oneway_shortest", "scores_unavailable",
    )


def test_explicit_shortest_legs_are_never_rewritten(service):
    """명시적으로 고른 최단 구간은 저장된 선호가 있어도 그대로 둔다."""
    context = service._build_cost_context(ACTIVE)
    given = ["oneway_shortest"]

    fill, reason = service._resolve_fill_leg_mode(given, ACTIVE, context)

    assert given == ["oneway_shortest"]   # 입력을 바꾸지 않는다
    assert (fill, reason) == ("oneway_preferred", None)  # 채우는 구간만 가중


# ── WaypointComposerEngine 전달 ─────────────────────────────────────────────


def _waypoint_input() -> WaypointRouteInput:
    return WaypointRouteInput(
        start_lat=37.50, start_lon=127.00, end_lat=37.51, end_lon=127.01,
        waypoints=[WaypointCoordinate(lat=37.505, lon=127.005)],
        leg_modes=["oneway_preferred", "oneway_shortest"],
        leg_target_km=[None, None],
    )


def test_composer_passes_context_to_astar_legs_only():
    """oneway_preferred leg에만 cost_context를 넘긴다 — 나머지는 순수 거리로 돈다."""
    G = prepared(scored_graph())
    context = request_context(G)
    composer = WaypointComposerEngine(_waypoint_input(), G, cost_context=context)

    assert composer._leg_cost_kwargs("oneway_preferred") == {"cost_context": context}
    assert composer._leg_cost_kwargs("oneway_shortest") == {}
    assert composer._leg_cost_kwargs("oneway_random") == {}


def test_composer_without_context_passes_nothing():
    composer = WaypointComposerEngine(_waypoint_input(), prepared(scored_graph()))

    assert composer.cost_context is None
    assert composer._leg_cost_kwargs("oneway_preferred") == {}


def test_leg_engine_accepts_the_forwarded_context():
    """전달 인자명이 실제 엔진 시그니처와 맞는지 고정한다."""
    G = prepared(scored_graph())
    context = request_context(G)

    from src.schema.route_schema import OnewayRouteInput

    inp = OnewayRouteInput(start_lat=0.0, start_lon=0.0, end_lat=0.0, end_lon=0.0, target_km=1.0)
    engine = OnewayAstarEngine(inp, G, **{"cost_context": context})

    assert engine.cost_context is context


def test_explicit_preferred_cannot_bypass_beam_exclusion(service):
    from src.interfaces.schema.walk_schema import Coordinate

    engine = service._build_engine(
        WalkMode.WAYPOINT,
        Coordinate(lat=37.5, lon=127.0),
        Coordinate(lat=37.51, lon=127.01),
        waypoints=[Coordinate(lat=37.505, lon=127.005)],
        leg_modes=["oneway_preferred", "oneway_random"],
        leg_target_km=[None, 3.0],
        preference=ACTIVE,
    )

    assert engine.cost_context is None
    assert engine.preference_skipped_reason == "beam_leg_present"
    assert engine.inp.leg_target_km == [None, 3.0]
    assert engine.experimental_detour_max_ratio is None


def test_direct_composer_also_excludes_beam_from_experimental_policy():
    inp = _waypoint_input().model_copy(update={
        "leg_modes": ["oneway_preferred", "oneway_random"],
        "leg_target_km": [None, 3.0],
    })
    G = prepared(scored_graph())
    engine = WaypointComposerEngine(
        inp, G, cost_context=request_context(G), experimental_detour_max_ratio=0.3,
    )

    assert not engine._preference_requested()
    assert engine._leg_cost_kwargs("oneway_preferred") == {}
    assert engine.preference_skipped_reason == "beam_leg_present"


def test_zero_coefficients_are_not_reported_as_missing_scores(service):
    preference = Weights(safety=0.0, comfort=0.0)
    context = service._build_cost_context(preference)

    assert context is None
    assert service._resolve_fill_leg_mode([], preference, context) == (
        "oneway_shortest", "zero_weights",
    )


@pytest.mark.parametrize("stored,speak,expected", [
    (None, False, (0.5, 0.0)),
    ((0.5, 0.5), False, (0.5, 0.5)),
    ((0.7, 0.8), False, (0.7, 0.8)),
    ((0.7, 0.8), True, (0.735, 0.8)),
    (None, True, (0.675, 0.0)),
])
def test_executor_forwards_survey_and_conversation_blend(service, monkeypatch, stored, speak, expected):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from src.agent.nodes.route_executor import RouteExecutor
    from src.repository.user.user_preference_repository import UserPreferenceRepository
    from src.schema.prewalk_schema import FeatureLabel, FeatureTag, Location, State, WayPointPreference

    preference = None if stored is None else SimpleNamespace(
        weights_safety=stored[0], weights_comfort=stored[1],
    )
    fetch = MagicMock(return_value=preference)
    monkeypatch.setattr(UserPreferenceRepository, "get_by_user_id", fetch)
    tool = SimpleNamespace(ainvoke=AsyncMock(return_value=[]))
    executor = RouteExecutor.__new__(RouteExecutor)
    executor.route_tool = SimpleNamespace(tool_map={"waypoint_route": tool})
    state = State(
        user_id=1, current_location=Location(lat=37.5, lon=127.0), mode=WalkMode.WAYPOINT,
        user_context=WayPointPreference(
            origin=Location(lat=37.5, lon=127.0),
            destination=Location(lat=37.51, lon=127.01),
        ),
        feature_labels={FeatureTag.SAFETY: FeatureLabel(
            preference_label="high", explicitness_label="explicit_soft",
        )} if speak else {},
    )

    asyncio.run(executor.run(state))
    args = tool.ainvoke.call_args.args[0]
    signal = args["preference"]
    assert (signal.safety, signal.comfort) == pytest.approx(expected)
    assert (args["custom_weights"].safety, args["custom_weights"].comfort) == pytest.approx(expected)
    # stored=None이면 run()의 첫 조회도 None이라 _build_weights가 한 번 더 조회한다
    # (미조회/명시적 None을 구분하는 센티널을 없앤 결과 — 결과값은 어느 쪽이든 같다).
    expected_calls = 2 if stored is None else 1
    assert fetch.call_count == expected_calls
    fetch.assert_called_with(1)
    context = service._build_cost_context(signal)
    assert context is not None
    assert context.alpha > 0
    # comfort는 명시적으로 고르기 전엔 0.0이 baseline이라(survey_service.py 기준),
    # 대화/설문 어느 쪽도 comfort를 안 건드린 경우(expected[1] == 0.0)는 beta도 0이다.
    if expected[1] > 0:
        assert context.beta > 0
    else:
        assert context.beta == 0.0


def test_executor_preserves_explicit_shortest_leg_without_target(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from src.agent.nodes.route_executor import RouteExecutor
    from src.repository.user.user_preference_repository import UserPreferenceRepository
    from src.schema.prewalk_schema import Location, State, WayPointPreference, WaypointLegPreference

    monkeypatch.setattr(UserPreferenceRepository, "get_by_user_id", lambda user_id: None)
    tool = SimpleNamespace(ainvoke=AsyncMock(return_value=[]))
    executor = RouteExecutor.__new__(RouteExecutor)
    executor.route_tool = SimpleNamespace(tool_map={"waypoint_route": tool})
    state = State(
        user_id=1, current_location=Location(lat=37.5, lon=127.0), mode=WalkMode.WAYPOINT,
        user_context=WayPointPreference(
            origin=Location(lat=37.5, lon=127.0), destination=Location(lat=37.51, lon=127.01),
            legs=[WaypointLegPreference(mode="oneway_shortest")],
        ),
    )

    asyncio.run(executor.run(state))
    args = tool.ainvoke.call_args.args[0]
    assert args["leg_modes"] == ["oneway_shortest"]
    assert args["leg_target_km"] == [None]
