"""
tests/unit/test_grasp_waypoint_alns.py

circular_grasp_waypoint_alns.py(GRASP + 팀원 독립 ALNS, waypoint_alns.py::alns_search
어댑터)에 대한 단위 테스트. 다른 3개 버전(local/vnd/vns)과 같은 5x5 합성 격자 그래프
fixture를 test_grasp_waypoint.py와 동일한 방식으로 이 파일 안에 독립적으로 구성한다
(conftest.py가 없는 이 저장소의 기존 관례 — 파일마다 자체 fixture를 둔다).

이 파일이 검증하지 않는 것:
  - waypoint_alns.py::alns_search 자체의 동작(제거·복구 규칙, SA 수락, segment 가중치
    갱신 등)은 tests/unit/test_waypoint_alns.py(팀원 구현, 이 작업으로 수정하지 않음)가
    이미 검증한다. 이 파일은 "그 함수와 grasp_waypoint_common.py/NetworkX 그래프 사이의
    어댑터가 올바른지"만 검증한다.
"""

import math

import networkx as nx
import pytest

from src.route_engine.engines.circular_grasp_waypoint_alns import (
    CircularGraspWaypointAlnsEngine,
    _build_alns_candidates,
    _make_cost_fn,
)
from src.route_engine.engines.grasp_waypoint_common import (
    GraspConfig,
    SelectionStatus,
    _CostCache,
    construct_initial_route,
)
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.engines.waypoint_pool import WaypointPoolGenerator
from src.route_engine.waypoint_alns import ALNSResult, OperatorStats
from src.route_engine.waypoint_types import WaypointOrder
from src.schema.route_schema import CircularRouteInput

_LAT_STEP = 0.0015  # 약 167m/step
_LON_STEP = 0.0018  # 약 160m/step (37.5도 위도 기준)
_ORIGIN_LAT = 37.5000
_ORIGIN_LON = 127.0000


def _node_id(row: int, col: int) -> int:
    return row * 5 + col + 1


def _coords(row: int, col: int) -> tuple[float, float]:
    return _ORIGIN_LAT + row * _LAT_STEP, _ORIGIN_LON + col * _LON_STEP


@pytest.fixture
def grid_graph() -> nx.Graph:
    """5x5 격자 그래프(실제 위경도 간격 부여) — test_grasp_waypoint.py::grid_graph와 동일 구성."""
    G = nx.Graph()
    for row in range(5):
        for col in range(5):
            lat, lon = _coords(row, col)
            G.add_node(_node_id(row, col), lat=lat, lon=lon)

    for row in range(5):
        for col in range(5):
            n = _node_id(row, col)
            if col < 4:
                e = _node_id(row, col + 1)
                lat1, lon1 = _coords(row, col)
                lat2, lon2 = _coords(row, col + 1)
                G.add_edge(n, e, length=PathUtils._haversine_m(lat1, lon1, lat2, lon2))
            if row < 4:
                s = _node_id(row + 1, col)
                lat1, lon1 = _coords(row, col)
                lat2, lon2 = _coords(row + 1, col)
                G.add_edge(n, s, length=PathUtils._haversine_m(lat1, lon1, lat2, lon2))
    return G


def _pool(G: nx.Graph, center_row: int, center_col: int, target_km: float):
    lat, lon = _coords(center_row, center_col)
    return WaypointPoolGenerator(G).build_pool(lat, lon, target_km)


# 엔진 통합 테스트 전용 목표거리. test_grasp_waypoint.py의 _ENGINE_TEST_TARGET_KM과
# 동일한 근거(target_km=0.6은 후보 풀이 구조적으로 너무 작아 2-경유지 조합이 항상
# 왕복 퇴화한다) — 같은 값을 그대로 쓴다.
_ENGINE_TEST_TARGET_KM = 1.2
_ENGINE_TEST_TARGET_M = _ENGINE_TEST_TARGET_KM * 1000


# ── _build_alns_candidates / _make_cost_fn 어댑터 ─────────────────────────

def test_build_alns_candidates_matches_pool_nodes_with_lat_lon(grid_graph):
    result = _pool(grid_graph, 2, 2, target_km=_ENGINE_TEST_TARGET_KM)
    assert result is not None

    candidates = _build_alns_candidates(grid_graph, result)
    assert {c["node_id"] for c in candidates} == set(result.pool_nodes)
    for c in candidates:
        assert c["lat"] == grid_graph.nodes[c["node_id"]]["lat"]
        assert c["lon"] == grid_graph.nodes[c["node_id"]]["lon"]


def test_make_cost_fn_handles_start_node_not_in_pool(grid_graph):
    """p1(start_node)은 waypoint_pool.py 설계상 pool_nodes에 없다 — cost(start,x)/cost(x,start)는
    pool_result.dist_from_p1으로 처리되고, pool_result.distance()처럼 ValueError가 나면 안 된다."""
    start_node = _node_id(2, 2)
    result = _pool(grid_graph, 2, 2, target_km=_ENGINE_TEST_TARGET_KM)
    assert result is not None
    cost = _make_cost_fn(result, start_node)

    some_node = result.pool_nodes[0]
    assert cost(start_node, some_node) == pytest.approx(result.dist_from_p1[some_node])
    assert cost(some_node, start_node) == pytest.approx(result.dist_from_p1[some_node])


def test_make_cost_fn_matches_pool_distance_between_two_pool_nodes(grid_graph):
    start_node = _node_id(2, 2)
    result = _pool(grid_graph, 2, 2, target_km=_ENGINE_TEST_TARGET_KM)
    assert result is not None
    assert len(result.pool_nodes) >= 2
    cost = _make_cost_fn(result, start_node)

    a, b = result.pool_nodes[0], result.pool_nodes[1]
    expected = result.distance(a, b)
    assert expected is not None  # 이 fixture에서는 항상 도달 가능(전수 격자)
    assert cost(a, b) == pytest.approx(expected)


class _FakePoolResult:
    """pool_result.distance()가 None(도달 불가)을 주는 상황을 진짜 그래프 기하 없이
    정확히 재현하기 위한 최소 대역(test_grasp_waypoint.py의 동명 헬퍼와 같은 목적)."""

    def __init__(self, dist_from_p1, pairwise):
        self.dist_from_p1 = dist_from_p1
        self._pairwise = pairwise

    def distance(self, u, v):
        return self._pairwise.get((u, v), self._pairwise.get((v, u)))


def test_make_cost_fn_returns_inf_for_unreachable_pair():
    """pool_result.distance()가 None(도달 불가)을 주면 cost()는 ALNS 계약대로 inf를 반환해야 한다."""
    fake = _FakePoolResult(dist_from_p1={2: 100.0, 3: 100.0}, pairwise={(2, 3): None})
    cost = _make_cost_fn(fake, start_node=1)
    assert cost(2, 3) == math.inf


# ── 엔진 통합 ────────────────────────────────────────────────────────────

def test_engine_returns_real_route_not_degenerate_fallback(grid_graph):
    inp = CircularRouteInput(start_lat=_ORIGIN_LAT, start_lon=_ORIGIN_LON, target_km=_ENGINE_TEST_TARGET_KM)
    engine = CircularGraspWaypointAlnsEngine(inp=inp, G=grid_graph, seed=42)
    start_node = _node_id(2, 2)

    nodes = engine.find_path(start_node, target_km=_ENGINE_TEST_TARGET_KM)
    assert nodes[0] == start_node
    assert nodes[-1] == start_node
    assert len(nodes) > 2  # 퇴화한 [start_node] 폴백이 아니라 실제로 p2·p3를 거친 순환 경로


def test_engine_sets_last_route_and_selection_status(grid_graph):
    inp = CircularRouteInput(start_lat=_ORIGIN_LAT, start_lon=_ORIGIN_LON, target_km=_ENGINE_TEST_TARGET_KM)
    engine = CircularGraspWaypointAlnsEngine(inp=inp, G=grid_graph, seed=42)
    start_node = _node_id(2, 2)

    engine.find_path(start_node, target_km=_ENGINE_TEST_TARGET_KM)
    assert engine.last_selection_status in (
        SelectionStatus.FEASIBLE, SelectionStatus.FALLBACK_DISTANCE, SelectionStatus.NO_VALID_WAYPOINT_PAIR,
    )
    if engine.last_selection_status != SelectionStatus.NO_VALID_WAYPOINT_PAIR:
        assert engine.last_route is not None
        assert engine.last_route.waypoint2 != engine.last_route.waypoint3


def test_engine_exposes_alns_operator_stats(grid_graph):
    """last_alns_stats에 destroy/repair operator 사용 횟수와 winning_iteration 상세가
    담기는지 확인한다(요청서 §4.4/§7 — operator별 사용 횟수 보고 요구)."""
    inp = CircularRouteInput(start_lat=_ORIGIN_LAT, start_lon=_ORIGIN_LON, target_km=_ENGINE_TEST_TARGET_KM)
    engine = CircularGraspWaypointAlnsEngine(inp=inp, G=grid_graph, seed=42)
    start_node = _node_id(2, 2)

    engine.find_path(start_node, target_km=_ENGINE_TEST_TARGET_KM)
    stats = engine.last_alns_stats
    assert stats is not None
    assert stats["alns_calls"] > 0
    assert set(stats["destroy_operator_uses"].keys()) <= {"random", "sequence"}
    assert set(stats["repair_operator_uses"].keys()) <= {"greedy", "random_order"}
    assert sum(stats["destroy_operator_uses"].values()) == stats["total_iterations"]
    if engine.last_selection_status == SelectionStatus.FEASIBLE:
        assert stats["winning_iteration"] is not None
        assert stats["winning_iteration"]["accepted"] in (True, False)


def test_engine_pool_generation_fails_gracefully_when_pool_is_empty(grid_graph):
    """target_km을 격자 간격(~160~170m)보다 훨씬 작게 주면 r_max(=target_m/2)가 1m
    미만이 돼 풀이 항상 비게 된다 — find_path는 [start_node] 폴백을 반환해야 한다.
    (find_path(start_node, target_km)는 inp.start_lat/lon이 아니라 start_node 인자로
    좌표를 얻으므로 — self.G.nodes[start_node] — inp 좌표를 어긋나게 하는 방식으로는
    이 경로를 트리거할 수 없다.)"""
    inp = CircularRouteInput(start_lat=_ORIGIN_LAT, start_lon=_ORIGIN_LON, target_km=0.001)
    engine = CircularGraspWaypointAlnsEngine(inp=inp, G=grid_graph, seed=42)
    start_node = _node_id(2, 2)

    nodes = engine.find_path(start_node, target_km=0.001)
    assert nodes == [start_node]
    assert engine.last_selection_status == SelectionStatus.NO_VALID_WAYPOINT_PAIR


def test_alns_result_violating_min_separation_is_rejected(grid_graph, monkeypatch):
    """실측 회귀(2026-08-30, target_km=5.0 다중 조건 검증): ALNS의 repair는
    _rank_p3_candidates의 최소거리 필터를 거치지 않으므로, better()로는 이겨도 P2-P3
    실제 거리가 min_waypoint_separation_ratio*target_m 미만인 (p2,p3)를 "best"로 고를
    수 있었다(30건 중 3건 위반, 2건은 feasible로 최종 채택까지 됨). alns_search를
    가짜 결과로 교체해 이 경로를 직접 재현하고, _improve_with_alns가 이제는 거부하는지
    확인한다."""
    start_node = _node_id(2, 2)
    pool_result = _pool(grid_graph, 2, 2, target_km=_ENGINE_TEST_TARGET_KM)
    assert pool_result is not None

    # 풀 안에서 실제로 서로 너무 가까운(최소거리 미만) 두 노드를 찾는다.
    cfg = GraspConfig()
    min_required = _ENGINE_TEST_TARGET_M * cfg.min_waypoint_separation_ratio
    too_close_pair = None
    for a in pool_result.pool_nodes:
        for b in pool_result.pool_nodes:
            if a == b:
                continue
            d = pool_result.distance(a, b)
            if d is not None and d < min_required:
                too_close_pair = (a, b)
                break
        if too_close_pair:
            break
    assert too_close_pair is not None, "이 fixture/target_km에서 테스트를 구성할 너무 가까운 쌍을 못 찾음"

    # 원래 GRASP 해는 임의로 고른 쌍이 아니라 실제 construct_initial_route로 만든다 —
    # 손으로 고른 (p2,p3)는 둘 다 출발점의 직접 이웃이면 왕복 퇴화로 prune_dead_ends가
    # 통째로 지워버려 BuildCycleRoute가 None을 반환하는 경우가 있었다(이 fixture에서
    # 실측 확인). 실제 GRASP 경로는 그런 퇴화가 없음을 이미 다른 테스트가 보장한다.
    cost_cache = _CostCache(grid_graph, mode="distance")
    original_route = None
    for attempt_seed in range(24):
        rng = __import__("random").Random(attempt_seed)
        construction = construct_initial_route(
            grid_graph, cost_cache, pool_result, start_node, _ENGINE_TEST_TARGET_M, rng, cfg,
        )
        if construction.route is not None and {construction.route.waypoint2, construction.route.waypoint3} != set(too_close_pair):
            original_route = construction.route
            break
    assert original_route is not None, "24회 재시도 후에도 유효한 원래 GRASP 해를 못 만듦"

    fake_best = WaypointOrder(waypoint_ids=too_close_pair, distance_m=1.0, error_m=0.0)  # error_m=0 → better()가 이김
    fake_result = ALNSResult(
        best=fake_best, current=fake_best, iterations=1, accepted_moves=1, failed_repairs=0,
        evaluated_orders=1, cost_calls=1, stop_reason="exact_target",
        destroy_stats=(OperatorStats("random", 1, 1.0),), repair_stats=(OperatorStats("greedy", 1, 1.0),),
    )
    monkeypatch.setattr(
        "src.route_engine.engines.circular_grasp_waypoint_alns.alns_search",
        lambda **kwargs: fake_result,
    )

    inp = CircularRouteInput(start_lat=_ORIGIN_LAT, start_lon=_ORIGIN_LON, target_km=_ENGINE_TEST_TARGET_KM)
    engine = CircularGraspWaypointAlnsEngine(inp=inp, G=grid_graph, seed=42, config=cfg)
    engine.cost_cache = cost_cache
    alns_candidates = _build_alns_candidates(grid_graph, pool_result)
    cost_fn = _make_cost_fn(pool_result, start_node)
    from src.route_engine.waypoint_alns import ALNSConfig
    alns_config = ALNSConfig(candidate_limit=cfg.rcl_size)

    result_route, accepted, _ = engine._improve_with_alns(
        original_route, alns_candidates, cost_fn, start_node, alns_config, _ENGINE_TEST_TARGET_M,
    )
    assert accepted is False
    assert result_route is original_route  # 최소거리를 어긴 ALNS 제안은 기각되고 원래 해가 그대로 유지됨


def test_alns_improvement_never_worsens_the_grasp_initial_route(grid_graph):
    """_improve_with_alns는 better()로 원래 GRASP 초기 해와 비교한 뒤에만 교체한다 —
    여러 seed에 걸쳐 최종 경로가 raw 구축 단계보다 절대 나빠지지 않아야 한다. (실측으로
    확인된 회귀: ALNS 결과를 검증 없이 그대로 채택하면 repeated_edge_ratio가 0.66→0.40
    같은 방향으로 악화될 수 있었다 — 이 테스트가 그 회귀를 막는다.)"""
    from src.route_engine.engines.grasp_waypoint_common import (
        _CostCache,
        better,
        construct_initial_route,
        evaluate_route,
    )
    from src.schema.route_schema import CircularRouteInput as _Inp

    start_node = _node_id(2, 2)
    target_m = _ENGINE_TEST_TARGET_M
    pool_result = _pool(grid_graph, 2, 2, target_km=_ENGINE_TEST_TARGET_KM)
    assert pool_result is not None

    inp = _Inp(start_lat=_ORIGIN_LAT, start_lon=_ORIGIN_LON, target_km=_ENGINE_TEST_TARGET_KM)
    engine = CircularGraspWaypointAlnsEngine(inp=inp, G=grid_graph, seed=42)
    cost_cache = _CostCache(grid_graph, mode="distance")

    checked = 0
    for seed in range(10):
        rng = __import__("random").Random(seed)
        construction = construct_initial_route(grid_graph, cost_cache, pool_result, start_node, target_m, rng, engine.config)
        if construction.route is None:
            continue
        checked += 1

        candidates = _build_alns_candidates(grid_graph, pool_result)
        cost_fn = _make_cost_fn(pool_result, start_node)
        from src.route_engine.waypoint_alns import ALNSConfig
        alns_config = ALNSConfig(iterations=20, candidate_limit=engine.config.rcl_size, seed=seed)

        improved, _accepted, _alns_result = engine._improve_with_alns(
            construction.route, candidates, cost_fn, start_node, alns_config, target_m
        )

        before = evaluate_route(construction.route, target_m, engine.config.distance_tolerance_m)
        after = evaluate_route(improved, target_m, engine.config.distance_tolerance_m)
        assert not better(before, after)  # after가 before보다 나빠지면 안 됨(같거나 더 좋아야 함)

    assert checked >= 5  # 최소 절반 이상의 seed에서 실제로 초기 해가 만들어졌는지(테스트 자체의 유효성 확인)
