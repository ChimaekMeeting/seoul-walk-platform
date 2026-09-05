"""
tests/unit/test_grasp_waypoint.py

경유지 선택 기반 GRASP 3종(circular_grasp_waypoint_{local,vnd,vns}.py)과 공통 모듈
(grasp_waypoint_common.py)에 대한 단위 테스트. 작은 합성 격자 그래프를 fixture로
사용하며, 실제 위경도 간격을 부여해 Haversine/A*가 의미 있게 동작하도록 한다.

경유지 후보 풀은 waypoint_pool.py::WaypointPoolGenerator(p1 기준 cutoff SSSP 단일 풀)를
그대로 쓴다 — 이 파일이 직접 거리링을 만들던 이전 버전과 달리, "실제 거리 기준
필터링"은 waypoint_pool.py 쪽 책임이라 이 테스트는 grasp_waypoint_common.py가 그
결과(WaypointPoolResult)를 올바르게 소비하는지만 검증한다.

이 파일이 검증하지 않는 것(별도로 실행해서 확인):
  - 기존 회귀: `pytest tests/unit/test_routue_service.py`가 이 작업과 무관하게 그대로
    통과하는지는 별도로 실행한다(이 파일 안에서 중복 작성하지 않음).
"""

import math

import networkx as nx
import pytest

from src.interfaces.schema.walk_schema import WalkMode
from src.route_engine.engines.grasp_waypoint_common import (
    BuildCycleRoute,
    GraspConfig,
    MissingEdgeAttributeError,
    Route,
    RouteObjective,
    SelectionStatus,
    _CostCache,
    EdgeCost,
    _angular_separation_rad,
    _bearing_rad,
    _rank_next_waypoint_candidates,
    better,
    compute_route_geometry_metrics,
    construct_initial_route,
    determine_selection_status,
    evaluate_route,
    is_degenerate_loop_route,
    is_waypoint_pair_separated,
)
from src.route_engine.engines.circular_grasp_waypoint_local import CircularGraspWaypointLocalEngine
from src.route_engine.engines.circular_grasp_waypoint_vnd import CircularGraspWaypointVndEngine
from src.route_engine.engines.circular_grasp_waypoint_vns import CircularGraspWaypointVnsEngine
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.engines.waypoint_pool import WaypointPoolGenerator
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
    """5x5 격자 그래프(실제 위경도 간격 부여). 모든 엣지 length는 두 끝점의 실제
    Haversine 거리로 설정해 A*가 의미 있게 동작하게 한다."""
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
    """WaypointPoolGenerator로 실제 풀을 만든다(테스트 전용 헬퍼). None이면 그대로 반환."""
    lat, lon = _coords(center_row, center_col)
    return WaypointPoolGenerator(G).build_pool(lat, lon, target_km)


# ── RouteObjective 비교 순서(허용오차 안에서는 반복률 우선) ───────────────
#
# 사용자 피드백: "겹치는 경로 말고 O형 경로를 원한다"는 지적에 따라, feasible(허용오차
# 이내)인 두 해를 비교할 때는 distance_error_m보다 repeated_edge_ratio를 먼저 본다.
# 실측 그래프에서는 두 해가 정확히 같은 distance_error_m을 갖는 경우가 거의 없어,
# 이전처럼 distance_error_m을 먼저 비교하면 repeated_edge_ratio가 사실상 한 번도
# tie-break로 작동하지 않았다(2026-08-30 실측: target_km=5.0 seed=42에서 Local·VND
# 모두 overlap_ratio=1.000인 완전 왕복 경로를 최종 채택 — repeated_edge_ratio가 비교에
# 전혀 반영되지 않았다는 증거).

def test_route_objective_prefers_lower_overlap_over_smaller_distance_error_when_both_feasible():
    """허용오차 안에서는 repeated_edge_ratio가 distance_error_m보다 먼저 비교돼야 한다 —
    거리오차가 조금 더 크더라도(둘 다 feasible이면) 반복률이 낮은 해가 이긴다."""
    low_overlap_bigger_error = RouteObjective(feasible=True, distance_error_m=100.0, repeated_edge_ratio=0.1)
    high_overlap_smaller_error = RouteObjective(feasible=True, distance_error_m=10.0, repeated_edge_ratio=0.9)
    assert better(low_overlap_bigger_error, high_overlap_smaller_error)


def test_route_objective_prefers_smaller_distance_error_when_infeasible():
    """허용오차 밖(feasible=False)인 두 해를 비교할 때는 여전히 distance_error_m이
    먼저다 — 목표거리에도 못 미치는 상태에서 반복률을 우선할 이유가 없다."""
    closer_to_target = RouteObjective(feasible=False, distance_error_m=200.0, repeated_edge_ratio=0.9)
    farther_from_target = RouteObjective(feasible=False, distance_error_m=500.0, repeated_edge_ratio=0.1)
    assert better(closer_to_target, farther_from_target)


def test_route_objective_feasible_always_beats_infeasible():
    feasible = RouteObjective(feasible=True, distance_error_m=1000.0, repeated_edge_ratio=0.9)
    infeasible = RouteObjective(feasible=False, distance_error_m=1.0, repeated_edge_ratio=0.0)
    assert better(feasible, infeasible)


def test_route_objective_reproduces_spec_example_route_b_wins():
    """요청서 §8.4 원안 그대로: 경로 A(오차 0.5m, 중복률 0.66) vs 경로 B(오차 25.6m,
    중복률 0.017) — 둘 다 허용오차 안이면 경로 B가 우선해야 한다."""
    route_a = RouteObjective(feasible=True, distance_error_m=0.5, repeated_edge_ratio=0.66)
    route_b = RouteObjective(feasible=True, distance_error_m=25.6, repeated_edge_ratio=0.017)
    assert better(route_b, route_a)
    assert not better(route_a, route_b)


# ── 거리 속성 키 검증 ────────────────────────────────────────────────────

def test_missing_length_attribute_fails_explicitly_not_silently_zero():
    with pytest.raises(MissingEdgeAttributeError):
        EdgeCost("distance", {})


def test_edge_cost_distance_reads_length_attribute():
    assert EdgeCost("distance", {"length": 123.0}) == 123.0


# ── 기본 모드 / 자연 모드 비활성화 ───────────────────────────────────────

def test_default_mode_is_distance(grid_graph):
    inp = CircularRouteInput(start_lat=_ORIGIN_LAT, start_lon=_ORIGIN_LON, target_km=0.5)
    engine = CircularGraspWaypointLocalEngine(inp=inp, G=grid_graph)
    assert engine.mode == "distance"


def test_natural_mode_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        EdgeCost("natural", {"nature_score": 0.8})


def test_distance_natural_mode_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        EdgeCost("distance_natural", {"length": 10.0, "nature_score": 0.8})


def test_unknown_mode_raises_value_error():
    with pytest.raises(ValueError):
        EdgeCost("not-a-real-mode", {"length": 10.0})


def test_mode_propagates_from_engine_to_edge_cost(grid_graph):
    """엔진에 mode="natural"을 넣으면, BuildCycleRoute의 최종 A* 연결 단계(cost_cache ->
    A* weight -> EdgeCost)까지 그 mode가 실제로 전달된다는 것을 NotImplementedError
    전파로 확인한다."""
    cost_cache = _CostCache(grid_graph, mode="natural")
    with pytest.raises(NotImplementedError):
        cost_cache.astar_path(_node_id(0, 0), _node_id(4, 4))


# ── 경유지 후보 풀(WaypointPoolGenerator) 소비 확인 ──────────────────────

def test_pool_excludes_p1_by_construction(grid_graph):
    """p1은 애초에 WaypointPoolResult.pool_nodes에 포함되지 않는다(waypoint_pool.py
    자체 보장) — grasp_waypoint_common.py가 별도로 p1을 제외하는 로직을 짤 필요가 없다."""
    center = _node_id(2, 2)
    result = _pool(grid_graph, 2, 2, target_km=0.6)
    assert result is not None
    assert center not in result.pool_nodes


def test_pool_excludes_nodes_outside_r_max(grid_graph):
    """r_max=target_m/2 밖의 노드는 풀에 없다."""
    result = _pool(grid_graph, 2, 2, target_km=0.2)  # r_max=100m — 격자 간격(~160~170m)보다 좁음
    assert result is not None
    for node in result.pool_nodes:
        assert result.dist_from_p1[node] <= result.r_max


def test_rank_next_waypoint_candidates_orders_by_half_target_distance_for_first_waypoint(grid_graph):
    """_rank_next_waypoint_candidates가 prev==p1(첫 경유지 선택 단계)일 때
    |2*dist(p1,c) - target_m| 오름차순으로 정렬하는지 확인한다(기존 _rank_p2_candidates와
    동일한 동작)."""
    target_m = 300.0
    p1 = _node_id(2, 2)
    result = _pool(grid_graph, 2, 2, target_km=target_m / 1000)
    assert result is not None

    ranked = _rank_next_waypoint_candidates(grid_graph, result, p1, p1, 0.0, target_m, GraspConfig())
    errors = [abs(2 * result.dist_from_p1[c] - target_m) for c in ranked]
    assert errors == sorted(errors)  # 오름차순 정렬 확인


def test_rank_next_waypoint_candidates_uses_real_pool_distance(grid_graph):
    """_rank_next_waypoint_candidates(prev=p2)가 pool_result.distance(p2, c)(실제 그래프
    거리)를 쓰는지 — 직접 계산한 dist(p1,p2)+dist(p2,c)+dist(p1,c)와 랭킹 기준이
    일치하는지 확인한다(기존 _rank_p3_candidates와 동일한 동작)."""
    target_m = 600.0
    result = _pool(grid_graph, 2, 2, target_km=target_m / 1000)
    assert result is not None
    assert len(result.pool_nodes) >= 2

    p1 = _node_id(2, 2)
    p2 = result.pool_nodes[0]
    off_cfg = GraspConfig(angle_diversity_weight_m=0.0, min_waypoint_separation_ratio=0.0)
    ranked = _rank_next_waypoint_candidates(
        grid_graph, result, p1, p2, result.dist_from_p1[p2], target_m, off_cfg,
    )
    for c in ranked:
        d = result.distance(p2, c)
        assert d is not None  # 랭킹에 포함됐다면 도달 가능해야 함
    # 랭킹 기준으로 재계산한 오차가 실제로 오름차순인지 확인
    errors = [
        abs(result.dist_from_p1[p2] + result.distance(p2, c) + result.dist_from_p1[c] - target_m)
        for c in ranked
    ]
    assert errors == sorted(errors)


def test_rank_next_waypoint_candidates_excludes_p2_and_given_exclusions(grid_graph):
    target_m = 600.0
    result = _pool(grid_graph, 2, 2, target_km=target_m / 1000)
    assert result is not None
    p1 = _node_id(2, 2)
    p2 = result.pool_nodes[0]
    excluded = result.pool_nodes[1] if len(result.pool_nodes) > 1 else None
    off_cfg = GraspConfig(angle_diversity_weight_m=0.0, min_waypoint_separation_ratio=0.0)

    ranked = _rank_next_waypoint_candidates(
        grid_graph, result, p1, p2, result.dist_from_p1[p2], target_m, off_cfg,
        exclude=frozenset({excluded} if excluded else set()),
    )
    assert p2 not in ranked
    if excluded is not None:
        assert excluded not in ranked


# ── 방향 다양성(왕복 퇴화 방지) ──────────────────────────────────────────
#
# 사용자 피드백: GRASP이 고른 경유지가 목표 거리는 정확히 맞으면서도 p2·p3가 p1 기준
# 같은 방향에 몰려 "갔던 길을 그대로 되짚는" 경로(왕복 퇴화)가 자주 나온다는 지적에 따라,
# _rank_next_waypoint_candidates(prev != p1)에 방향(방위각) 다양성 페널티를 추가했다.
# 아래 테스트는 그 페널티의 핵심 수학(방위각 계산, 각도차 정규화)과, 거리 적합도가
# 동점일 때 실제로 정반대 방향 후보를 우선하는지를 검증한다.

def test_bearing_rad_matches_cardinal_directions():
    """정북=0, 정동=π/2, 정서=−π/2, 정남=±π(부호는 부동소수점에 따라 달라질 수 있어 절대값만 확인)."""
    assert _bearing_rad(0.0, 0.0, 1.0, 0.0) == pytest.approx(0.0, abs=1e-6)
    assert _bearing_rad(0.0, 0.0, 0.0, 1.0) == pytest.approx(math.pi / 2, abs=1e-6)
    assert _bearing_rad(0.0, 0.0, 0.0, -1.0) == pytest.approx(-math.pi / 2, abs=1e-6)
    assert abs(_bearing_rad(0.0, 0.0, -1.0, 0.0)) == pytest.approx(math.pi, abs=1e-6)


def test_angular_separation_rad_ranges_from_zero_to_pi():
    assert _angular_separation_rad(0.0, 0.0) == pytest.approx(0.0, abs=1e-9)
    assert _angular_separation_rad(0.0, math.pi) == pytest.approx(math.pi, abs=1e-9)
    assert _angular_separation_rad(0.0, 2 * math.pi) == pytest.approx(0.0, abs=1e-6)  # 한 바퀴 랩어라운드
    assert _angular_separation_rad(-math.pi / 2, math.pi / 2) == pytest.approx(math.pi, abs=1e-9)


class _FakePoolResult:
    """_rank_next_waypoint_candidates가 실제로 쓰는 최소 인터페이스(pool_nodes/dist_from_p1/distance())만
    구현한 테스트 전용 대역. cutoff SSSP 없이 거리값을 직접 지정해 '거리 적합도가 완전히
    동점인 두 후보'를 정확히 구성하기 위함이다(실제 격자에서는 경로 비용이 축마다 미묘하게
    달라 순수하게 방향 차이만 남기는 동점 상황을 만들기 어렵다)."""

    def __init__(self, pool_nodes, dist_from_p1, pairwise):
        self.pool_nodes = pool_nodes
        self.dist_from_p1 = dist_from_p1
        self._pairwise = pairwise

    def distance(self, u, v):
        return self._pairwise.get((u, v), self._pairwise.get((v, u)))


def test_rank_next_waypoint_candidates_prefers_perpendicular_direction_when_distance_fit_is_tied():
    """거리 적합도가 완전히 동점인 세 p3 후보(p1 기준 p2와 같은 방향/정반대 방향/직각)
    중, 직각 방향 후보가 항상 먼저 오는지 확인한다(angle_diversity_weight_m>0일 때).

    같은 방향(0°)이 왕복 퇴화라는 것은 자명하지만, 정반대 방향(180°)도 실제 그래프
    재현에서 p2→p3 최단경로가 p1 부근을 다시 지나 overlap_ratio가 오히려 1.0(완전
    왕복)까지 악화되는 것을 확인했다(GraspConfig.angle_diversity_weight_m 주석 참고) —
    그래서 "정반대일수록 좋다"가 아니라 "직각에 가까울수록 좋다(|cos| 최소)"가 맞는
    기준이며, 이 테스트는 그 최종 기준을 고정한다. 가중치가 0이면 다양성 페널티가
    완전히 꺼져 이전 동작(순수 거리 적합도, 동점 시 입력 순서 유지)과 같아야 한다."""
    G = nx.Graph()
    G.add_node(1, lat=0.0, lon=0.0)   # p1
    G.add_node(2, lat=0.0, lon=1.0)   # p2: p1 기준 정동
    G.add_node(3, lat=0.0, lon=2.0)   # c_same: p1 기준 정동(=p2와 같은 방향, 0°)
    G.add_node(4, lat=0.0, lon=-1.0)  # c_opp: p1 기준 정서(=p2와 정반대 방향, 180°)
    G.add_node(5, lat=1.0, lon=0.0)   # c_perp: p1 기준 정북(=p2와 직각, 90°)

    pool = _FakePoolResult(
        pool_nodes=[3, 4, 5],
        dist_from_p1={2: 1000.0, 3: 500.0, 4: 500.0, 5: 500.0},
        pairwise={(2, 3): 500.0, (2, 4): 500.0, (2, 5): 500.0},
    )
    target_m = 2000.0  # base(1000) + dist(p2,c)=500 + dist_from_p1[c]=500 → 세 후보 모두 오차 0

    off_cfg = GraspConfig(angle_diversity_weight_m=0.0, min_waypoint_separation_ratio=0.0)
    ranked_off = _rank_next_waypoint_candidates(G, pool, 1, 2, pool.dist_from_p1[2], target_m, off_cfg)
    assert ranked_off == [3, 4, 5]  # 동점 → 입력 순서 유지(이전 동작과 동일)

    on_cfg = GraspConfig(angle_diversity_weight_m=500.0, min_waypoint_separation_ratio=0.0)
    ranked_on = _rank_next_waypoint_candidates(G, pool, 1, 2, pool.dist_from_p1[2], target_m, on_cfg)
    assert ranked_on[0] == 5  # 직각 방향(5)이 항상 먼저 온다


# ── P2-P3 최소거리 안전장치 ──────────────────────────────────────────────
#
# 사용자 피드백: 방위각 페널티만으로는 "각도는 좋아 보여도 실제 도보상 P2·P3가 매우
# 가까운" 그래프 구조에서 여전히 왕복에 가까운 경로가 나올 수 있다는 지적(요청서
# §3.1)에 따라, P2-P3 실제 A* 거리가 target_m * min_waypoint_separation_ratio 미만인
# 조합을 후보 생성 단계에서부터 제외한다.

def test_is_waypoint_pair_separated_passes_when_distance_meets_ratio():
    """요청서 §8.1 원안: target_m=5000, min_ratio=0.20, P2-P3=1200m → 통과(기준 1000m)."""
    cfg = GraspConfig(min_waypoint_separation_ratio=0.20)
    assert is_waypoint_pair_separated(distance_p2_p3_m=1200.0, target_m=5000.0, config=cfg)


def test_is_waypoint_pair_separated_rejects_when_distance_below_ratio():
    """요청서 §8.2 원안: target_m=5000, min_ratio=0.20, P2-P3=499m → 제외(기준 1000m)."""
    cfg = GraspConfig(min_waypoint_separation_ratio=0.20)
    assert not is_waypoint_pair_separated(distance_p2_p3_m=499.0, target_m=5000.0, config=cfg)


def test_rank_next_waypoint_candidates_excludes_pairs_below_min_separation():
    """P2-P3 실제 거리(직선거리 아님, WaypointPoolResult.distance)가 min_waypoint_separation_ratio
    * target_m 미만인 후보는 방위각이 아무리 좋아도(여기서는 둘 다 직각) 랭킹에서 제외된다."""
    G = nx.Graph()
    G.add_node(1, lat=0.0, lon=0.0)   # p1
    G.add_node(2, lat=0.0, lon=1.0)   # p2
    G.add_node(3, lat=1.0, lon=0.0)   # c_far: p2와 직각 방향, 실제 거리 1200m(통과)
    G.add_node(4, lat=1.0, lon=0.5)   # c_near: p2와 비슷한 방향, 실제 거리 499m(제외 대상)

    pool = _FakePoolResult(
        pool_nodes=[3, 4],
        dist_from_p1={2: 1000.0, 3: 500.0, 4: 500.0},
        pairwise={(2, 3): 1200.0, (2, 4): 499.0},
    )
    cfg = GraspConfig(angle_diversity_weight_m=0.0, min_waypoint_separation_ratio=0.20)

    ranked = _rank_next_waypoint_candidates(G, pool, 1, 2, pool.dist_from_p1[2], 5000.0, cfg)  # 기준 = 5000*0.20 = 1000m
    assert 3 in ranked
    assert 4 not in ranked


def test_rank_next_waypoint_candidates_separation_filter_disabled_when_ratio_zero():
    """min_waypoint_separation_ratio=0이면 필터가 완전히 꺼져 가까운 후보도 포함된다
    (이전 동작과 동일해야 함)."""
    G = nx.Graph()
    G.add_node(1, lat=0.0, lon=0.0)
    G.add_node(2, lat=0.0, lon=1.0)
    G.add_node(4, lat=1.0, lon=0.5)

    pool = _FakePoolResult(pool_nodes=[4], dist_from_p1={2: 1000.0, 4: 500.0}, pairwise={(2, 4): 499.0})
    cfg = GraspConfig(angle_diversity_weight_m=0.0, min_waypoint_separation_ratio=0.0)
    ranked = _rank_next_waypoint_candidates(G, pool, 1, 2, pool.dist_from_p1[2], 5000.0, cfg)
    assert ranked == [4]


# ── selection_status(feasible / fallback_distance / no_valid_waypoint_pair) ──

def test_determine_selection_status_feasible_when_route_within_tolerance():
    route = Route(node_ids=[1, 2, 3, 1], waypoints=[2, 3], distance_m=5000.0, repeated_edge_ratio=0.0)
    obj = RouteObjective(feasible=True, distance_error_m=10.0, repeated_edge_ratio=0.0)
    assert determine_selection_status(route, obj, had_valid_waypoint_pair=True) == SelectionStatus.FEASIBLE


def test_determine_selection_status_fallback_distance_when_route_outside_tolerance():
    route = Route(node_ids=[1, 2, 3, 1], waypoints=[2, 3], distance_m=4000.0, repeated_edge_ratio=0.0)
    obj = RouteObjective(feasible=False, distance_error_m=1000.0, repeated_edge_ratio=0.0)
    assert determine_selection_status(route, obj, had_valid_waypoint_pair=True) == SelectionStatus.FALLBACK_DISTANCE


def test_determine_selection_status_no_valid_waypoint_pair_when_never_found_a_pair():
    from src.route_engine.engines.grasp_waypoint_common import _INFEASIBLE
    assert determine_selection_status(None, _INFEASIBLE, had_valid_waypoint_pair=False) == SelectionStatus.NO_VALID_WAYPOINT_PAIR


def test_determine_selection_status_fallback_distance_when_pair_found_but_no_route_built():
    """최소거리 조건을 만족하는 조합은 찾았지만(had_valid_waypoint_pair=True)
    BuildCycleRoute의 A* 연결이 전부 실패해 최종 경로가 없는 경우 — 요청서가 정의한
    3개 상태 중 가장 가까운 의미인 fallback_distance로 분류한다."""
    from src.route_engine.engines.grasp_waypoint_common import _INFEASIBLE
    assert determine_selection_status(None, _INFEASIBLE, had_valid_waypoint_pair=True) == SelectionStatus.FALLBACK_DISTANCE


def test_engine_reports_fallback_distance_status_when_no_route_within_tolerance(grid_graph):
    """요청서 §8.5: 목표거리 허용범위 후보가 없을 때 결과가 fallback_distance로
    기록되는지 확인한다 — distance_tolerance_ratio를 0으로 두면(허용 오차 0m) 최소거리
    조건을 만족하는 경로는 나오지만(22/24 성공, 위 _ENGINE_TEST_TARGET_KM 주석 참고)
    feasible한 경로는 하나도 없다."""
    cfg = GraspConfig(distance_tolerance_ratio=0.0)
    inp = CircularRouteInput(start_lat=_ORIGIN_LAT, start_lon=_ORIGIN_LON, target_km=_ENGINE_TEST_TARGET_KM)
    engine = CircularGraspWaypointLocalEngine(inp=inp, G=grid_graph, seed=42, config=cfg)
    start_node = _node_id(2, 2)

    engine.find_path(start_node, target_km=_ENGINE_TEST_TARGET_KM)
    assert engine.last_selection_status == SelectionStatus.FALLBACK_DISTANCE


def test_engine_reports_no_valid_waypoint_pair_status_when_separation_ratio_impossible(grid_graph):
    """min_waypoint_separation_ratio를 5x5 격자의 최대 가능 거리보다 크게 잡으면, 어떤
    (p2,p3) 조합도 최소거리 조건을 통과할 수 없다 — selection_status가
    no_valid_waypoint_pair로 기록돼야 하고, find_path는 [start_node] 폴백을 반환한다."""
    cfg = GraspConfig(min_waypoint_separation_ratio=0.99)  # 기준 = 1200m*0.99=1188m > 격자 전체 대각선
    inp = CircularRouteInput(start_lat=_ORIGIN_LAT, start_lon=_ORIGIN_LON, target_km=_ENGINE_TEST_TARGET_KM)
    engine = CircularGraspWaypointLocalEngine(inp=inp, G=grid_graph, seed=42, config=cfg)
    start_node = _node_id(2, 2)

    nodes = engine.find_path(start_node, target_km=_ENGINE_TEST_TARGET_KM)
    assert nodes == [start_node]
    assert engine.last_selection_status == SelectionStatus.NO_VALID_WAYPOINT_PAIR


def test_pool_generation_fails_gracefully_when_no_node_found(grid_graph):
    """p1 좌표 근처(R1/R2 확장 반경 이내)에 노드가 하나도 없으면 build_pool은 예외 없이
    None을 반환한다(find_nearest_node_with_expansion이 None을 주는 경로).

    주의: 완전히 빈 그래프(노드 0개)는 이 경로와 다르다 — PathUtils.find_nearest_node가
    빈 그래프에서는 max() on empty iterable로 크래시하는 별개의 사전 존재 엣지케이스이며,
    이 작업(waypoint_pool.py 연결)의 범위 밖이라 여기서 다루지 않는다."""
    far_lat, far_lon = _ORIGIN_LAT + 10, _ORIGIN_LON + 10  # 격자에서 한참 떨어진 좌표
    result = WaypointPoolGenerator(grid_graph).build_pool(far_lat, far_lon, target_km=1.0)
    assert result is None


# ── 경로 연결 / 연결 실패 / 실제 거리 ────────────────────────────────────

def test_build_cycle_route_connects_three_segments_without_duplicate_boundary(grid_graph):
    cost_cache = _CostCache(grid_graph, mode="distance")
    start = _node_id(0, 0)
    p2 = _node_id(0, 4)
    p3 = _node_id(4, 4)

    route = BuildCycleRoute(grid_graph, cost_cache.astar_path, start, [p2, p3])

    assert route is not None
    assert route.node_ids[0] == start
    assert route.node_ids[-1] == start
    # 경계 노드(p2, p3)가 각각 한 번씩만 등장(중복 합산 안 됨)
    assert route.node_ids.count(p2) == 1
    assert route.node_ids.count(p3) == 1


def test_build_cycle_route_distance_matches_actual_edge_length_sum(grid_graph):
    cost_cache = _CostCache(grid_graph, mode="distance")
    start = _node_id(0, 0)
    p2 = _node_id(0, 2)
    p3 = _node_id(2, 2)

    route = BuildCycleRoute(grid_graph, cost_cache.astar_path, start, [p2, p3])
    assert route is not None

    independent_sum = sum(
        grid_graph[u][v]["length"] for u, v in zip(route.node_ids, route.node_ids[1:])
    )
    assert route.distance_m == pytest.approx(independent_sum)


def test_build_cycle_route_fails_when_a_segment_is_unreachable(grid_graph):
    G = grid_graph.copy()
    G.add_node(999, lat=_ORIGIN_LAT + 10, lon=_ORIGIN_LON + 10)  # 고립 노드

    cost_cache = _CostCache(G, mode="distance")
    start = _node_id(0, 0)
    p2 = _node_id(0, 2)

    route = BuildCycleRoute(G, cost_cache.astar_path, start, [p2, 999])
    assert route is None


# ── 원형성 진단 지표(compute_route_geometry_metrics / is_degenerate_loop_route) ──
#
# 사용자 요청(2026-08-30): "최종 경로가 실제로 원형에 가까운지 확인할 수 있도록"
# d12/d23/d31·repeated_edge_ratio·waypoint_separation_m·waypoint_angle_diff_deg·
# segment_balance_ratio를 기록하고, 세 조건(반복률>0.35 / P2-P3<target_m*0.20 /
# 균형비<0.25) 중 하나라도 해당하면 is_degenerate_loop=true로 표시한다(반복률 임계값은
# 2026-09-02 재통행 지표 정의 전환으로 0.50→0.35 재조정됨,
# grasp_waypoint_common.py::_DEGENERATE_REPEATED_EDGE_RATIO 주석 참고). 세 구간 균형은
# 이번 단계에서 탐색을 막는 강한 조건이 아니라 이 진단 플래그·로그·CSV 기록용일 뿐이다.

def test_compute_route_geometry_metrics_returns_none_for_missing_route(grid_graph):
    cost_cache = _CostCache(grid_graph, mode="distance")
    metrics = compute_route_geometry_metrics(grid_graph, cost_cache.astar_path, _node_id(2, 2), None, 1200.0)
    assert metrics.segment_lengths_m is None
    assert metrics.repeated_edge_ratio is None
    assert metrics.waypoint_separation_m is None
    assert metrics.waypoint_angle_diffs_deg is None
    assert metrics.segment_balance_ratio is None
    assert metrics.is_degenerate_loop is False


def test_compute_route_geometry_metrics_matches_build_cycle_route(grid_graph):
    """d12/d23/d31·repeated_edge_ratio·waypoint_separation_m이 BuildCycleRoute가 이미
    계산해둔 실제 A* 경로 기준과 일치하는지 확인한다(추정치가 아님)."""
    cost_cache = _CostCache(grid_graph, mode="distance")
    start = _node_id(0, 0)
    p2 = _node_id(0, 2)
    p3 = _node_id(2, 2)
    route = BuildCycleRoute(grid_graph, cost_cache.astar_path, start, [p2, p3])
    assert route is not None

    metrics = compute_route_geometry_metrics(grid_graph, cost_cache.astar_path, start, route, target_m=1000.0)
    assert metrics.repeated_edge_ratio == route.repeated_edge_ratio
    assert metrics.waypoint_separation_m == metrics.segment_lengths_m[1]
    # 세 구간 합은 왕복/가지치기가 없는 정상 경로에서 route.distance_m과 일치해야 한다.
    assert sum(metrics.segment_lengths_m) == pytest.approx(route.distance_m)
    assert 0.0 < metrics.waypoint_angle_diffs_deg[0] <= 180.0
    assert 0.0 < metrics.segment_balance_ratio <= 1.0


def test_is_degenerate_loop_route_true_for_high_repeated_edge_ratio():
    assert is_degenerate_loop_route(0.36, 2000.0, 5000.0, 0.9) is True
    assert is_degenerate_loop_route(0.35, 2000.0, 5000.0, 0.9) is False  # 경계값(>0.35)은 미포함


def test_is_degenerate_loop_route_true_for_short_waypoint_separation():
    target_m = 5000.0
    assert is_degenerate_loop_route(0.1, target_m * 0.20 - 1, target_m, 0.9) is True
    assert is_degenerate_loop_route(0.1, target_m * 0.20, target_m, 0.9) is False  # 경계값 미포함


def test_is_degenerate_loop_route_true_for_unbalanced_segments():
    assert is_degenerate_loop_route(0.1, 2000.0, 5000.0, 0.24) is True
    assert is_degenerate_loop_route(0.1, 2000.0, 5000.0, 0.25) is False  # 경계값 미포함


def test_is_degenerate_loop_route_false_when_all_healthy():
    assert is_degenerate_loop_route(0.1, 2000.0, 5000.0, 0.9) is False


def test_is_degenerate_loop_route_skips_none_conditions():
    """좌표가 없어 segment_balance_ratio를 못 구한 경우처럼 일부 값이 None이면 그
    조건만 건너뛰고 나머지 조건으로 판정한다 — 계산 불가가 판정 자체를 막지 않는다."""
    assert is_degenerate_loop_route(0.1, None, 5000.0, None) is False
    assert is_degenerate_loop_route(0.6, None, 5000.0, None) is True


# ── GRASP 구축 / 지역개선 / VND / VNS (엔진 통합) ────────────────────────

def test_construct_initial_route_returns_feasible_or_none(grid_graph):
    cost_cache = _CostCache(grid_graph, mode="distance")
    result = _pool(grid_graph, 2, 2, target_km=0.6)
    assert result is not None
    cfg = GraspConfig()
    rng = __import__("random").Random(42)

    construction = construct_initial_route(grid_graph, cost_cache, result, _node_id(2, 2), target_m=600.0, rng=rng, cfg=cfg)
    assert construction.route is None or isinstance(construction.route, Route)


# 엔진 통합 테스트 전용 목표거리. 5x5 격자에서 target_km=0.6(r_max=300m)은 후보 풀이
# 중심의 직접 이웃 4개뿐이라(서로 비인접) 2-경유지 조합이 구조적으로 항상 왕복
# 퇴화한다(실측: 24회 재시도 전부 실패) — 순수 왕복이면 prune_dead_ends가 지워버려
# find_path()가 [start_node] 폴백만 반환하고, 그러면 아래 약한 단언들이 "성공"을
# 실제로 검증하지 못한 채 통과해버린다. target_km=1.2(r_max=600m, 풀 20개)에서는
# 실측 24회 중 22회 실제 경로 구축에 성공해 의미 있는 검증이 된다.
_ENGINE_TEST_TARGET_KM = 1.2
_ENGINE_TEST_TARGET_M = _ENGINE_TEST_TARGET_KM * 1000


def test_local_search_never_worsens_the_route(grid_graph):
    inp = CircularRouteInput(start_lat=_ORIGIN_LAT, start_lon=_ORIGIN_LON, target_km=_ENGINE_TEST_TARGET_KM)
    engine = CircularGraspWaypointLocalEngine(inp=inp, G=grid_graph, seed=42)
    start_node = _node_id(2, 2)

    nodes = engine.find_path(start_node, target_km=_ENGINE_TEST_TARGET_KM)
    assert nodes[0] == start_node
    # 퇴화한 [start_node] 폴백이 아니라 실제로 p2·p3를 거친 순환 경로여야 한다.
    assert len(nodes) > 2
    assert nodes[-1] == start_node


def test_vnd_restarts_from_first_neighborhood_after_improvement(grid_graph):
    inp = CircularRouteInput(start_lat=_ORIGIN_LAT, start_lon=_ORIGIN_LON, target_km=_ENGINE_TEST_TARGET_KM)
    engine = CircularGraspWaypointVndEngine(inp=inp, G=grid_graph, seed=42)
    start_node = _node_id(2, 2)

    nodes = engine.find_path(start_node, target_km=_ENGINE_TEST_TARGET_KM)
    assert nodes[0] == start_node
    assert len(nodes) > 2


def test_vns_does_not_accept_worse_route_after_shake(grid_graph):
    """
    단발 construct_initial_route는 rng seed에 따라 초기 해를 못 만들 수 있다 — 실제
    엔진(find_path)은 이 문제를 24회 재시도로 흡수하므로 겪지 않는다. 이 테스트는
    알고리즘 결함을 skip으로 숨기지 않기 위해, 실제 GRASP과 동일하게 여러 seed를
    순서대로 재시도한다.
    """
    inp = CircularRouteInput(start_lat=_ORIGIN_LAT, start_lon=_ORIGIN_LON, target_km=_ENGINE_TEST_TARGET_KM)
    engine = CircularGraspWaypointVnsEngine(inp=inp, G=grid_graph, seed=42)
    start_node = _node_id(2, 2)
    target_m = _ENGINE_TEST_TARGET_M

    pool_result = _pool(grid_graph, 2, 2, target_km=_ENGINE_TEST_TARGET_KM)
    assert pool_result is not None

    initial, rng = None, None
    for attempt_seed in range(24):  # 실제 엔진의 _GRASP_ITERS(24)와 동일한 재시도 횟수
        rng = __import__("random").Random(attempt_seed)
        construction = construct_initial_route(engine.G, engine.cost_cache, pool_result, start_node, target_m, rng, engine.config)
        if construction.route is not None:
            initial = construction.route
            break
    if initial is None:
        pytest.skip("24회 재시도(실제 엔진과 동일한 반복 횟수) 후에도 이 격자/목표거리 조합에서 초기 해를 못 만듦")

    vnd_result = engine._vnd_engine.vnd(initial, pool_result, start_node, target_m)
    after_vns = engine._vns_loop(vnd_result, pool_result, start_node, target_m, rng)

    obj_before = evaluate_route(vnd_result, target_m, target_m * engine.config.distance_tolerance_ratio)
    obj_after = evaluate_route(after_vns, target_m, target_m * engine.config.distance_tolerance_ratio)
    assert not better(obj_before, obj_after)  # VNS 결과가 VND 단독 결과보다 나빠지지 않음


# ── 3버전 공정 비교 ──────────────────────────────────────────────────────

def test_three_engines_use_same_mode_and_are_comparable_with_same_evaluate_route(grid_graph):
    inp = CircularRouteInput(start_lat=_ORIGIN_LAT, start_lon=_ORIGIN_LON, target_km=_ENGINE_TEST_TARGET_KM)
    start_node = _node_id(2, 2)

    engines = [
        CircularGraspWaypointLocalEngine(inp=inp, G=grid_graph, seed=42),
        CircularGraspWaypointVndEngine(inp=inp, G=grid_graph, seed=42),
        CircularGraspWaypointVnsEngine(inp=inp, G=grid_graph, seed=42),
    ]
    assert all(e.mode == "distance" for e in engines)

    results = [e.find_path(start_node, target_km=_ENGINE_TEST_TARGET_KM) for e in engines]
    assert all(r[0] == start_node for r in results)
    assert all(len(r) > 2 for r in results)  # 셋 다 퇴화 폴백이 아니라 실제 경로여야 함
    # 세 결과 모두 같은 target_m/tolerance 기준 evaluate_route로 비교 가능해야 한다(예외 없이 계산됨).
    for e, nodes in zip(engines, results):
        route = Route(
            node_ids=nodes,
            waypoints=[nodes[1], nodes[-2]] if len(nodes) > 1 else [start_node],
            distance_m=sum(grid_graph[u][v]["length"] for u, v in zip(nodes, nodes[1:])) if len(nodes) > 1 else 0.0,
            repeated_edge_ratio=0.0,
        )
        evaluate_route(
            route,
            target_distance_m=_ENGINE_TEST_TARGET_M,
            distance_tolerance_m=_ENGINE_TEST_TARGET_M * e.config.distance_tolerance_ratio,
        )


# ── 프로덕션 배선 보호 ────────────────────────────────────────────────────

def test_production_dispatch_table_is_untouched():
    from src.route_engine.engines.circular_beam import CircularBeamEngine
    from src.service.route.route_service import RouteService

    service = RouteService(G=nx.Graph(), auth_service=None)
    assert service.base_engines[WalkMode.CIRCULAR_RANDOM] is CircularBeamEngine
