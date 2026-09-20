"""
tests/unit/test_waypoint_engine_assembly.py

waypoint_engine_assembly.py::WaypointEngine의 생성자 검증과 반환 규약(이슈 #443의
"최종 경로 1개 + 후보 2개")을 확인한다. 조합별 실제 경로 탐색 품질은
test_grasp_waypoint.py / test_grasp_waypoint_alns.py가 이미 검증하므로 여기서 반복하지
않는다(파일마다 자체 fixture를 두는 이 저장소의 기존 관례를 따른다).
"""

import networkx as nx
import pytest

import src.route_engine.engines.waypoint_engine_assembly as assembly
from src.interfaces.schema.walk_schema import WalkMode, WalkRouteStatus
from src.route_engine.engines.grasp_waypoint_common import RouteObjective
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.engines.waypoint_engine_assembly import (
    CANDIDATE_COUNT,
    MULTI_CANDIDATE_COMBOS,
    WaypointEngine,
)
from src.route_engine.engines.waypoint_refinement import (
    OPTIONS_AWARE_REFINEMENTS,
    REFINEMENT_REGISTRY,
)
from src.route_engine.waypoint_route_builder import Route
from src.schema.route_schema import CircularRouteInput, OnewayRouteInput

_IGNORES_OPTIONS = sorted(set(REFINEMENT_REGISTRY) - OPTIONS_AWARE_REFINEMENTS)

# 주입을 받는 정제마다 그 정제가 실제로 아는 키 하나. OPTIONS_AWARE_REFINEMENTS에 새
# 정제를 추가하면 아래 test_every_options_aware_refinement_has_a_sample이 이 표를 함께
# 채우도록 강제한다.
_VALID_OPTIONS = {
    "alns": {"iterations": 10},
    "vns": {"max_shake_level": 2},
}


@pytest.fixture
def tiny_graph() -> nx.Graph:
    """생성자 검증만 하므로 경로 탐색이 가능할 필요는 없다 — PathUtils/_CostCache/
    WaypointPoolGenerator는 생성자에서 그래프를 참조만 하고 훑지 않는다."""
    G = nx.Graph()
    G.add_node(1, lat=37.5000, lon=127.0000)
    G.add_node(2, lat=37.5015, lon=127.0000)
    G.add_edge(1, 2, length=166.0)
    return G


def _inp() -> CircularRouteInput:
    return CircularRouteInput(start_lat=37.5, start_lon=127.0, target_km=1.2)


def test_unknown_construction_is_rejected(tiny_graph):
    with pytest.raises(ValueError, match="construction"):
        WaypointEngine(inp=_inp(), G=tiny_graph, construction="nope")


def test_unknown_refinement_is_rejected(tiny_graph):
    with pytest.raises(ValueError, match="refinement"):
        WaypointEngine(inp=_inp(), G=tiny_graph, refinement="nope")


@pytest.mark.parametrize("refinement", _IGNORES_OPTIONS)
def test_options_on_refinement_that_ignores_them_is_rejected(tiny_graph, refinement):
    """options를 해석하지 않는 정제에 주입하면 조용히 무시되는 대신 즉시 실패해야 한다 —
    스윕 스크립트가 beam×vns 조합에 alns 노브를 잘못 실어 보내도 아무 일도 일어나지 않던
    빈틈을 막는다."""
    with pytest.raises(ValueError, match="options"):
        WaypointEngine(
            inp=_inp(), G=tiny_graph, refinement=refinement,
            refinement_options={"iterations": 10},
        )


def test_every_options_aware_refinement_has_a_sample():
    """주입 대상을 늘리면 아래 수용 테스트도 함께 늘어나야 한다."""
    assert set(_VALID_OPTIONS) == set(OPTIONS_AWARE_REFINEMENTS)


@pytest.mark.parametrize("refinement", sorted(OPTIONS_AWARE_REFINEMENTS))
def test_options_on_options_aware_refinement_is_accepted(tiny_graph, refinement):
    options = _VALID_OPTIONS[refinement]
    engine = WaypointEngine(
        inp=_inp(), G=tiny_graph, refinement=refinement, refinement_options=options,
    )
    assert engine.refinement_options == options


@pytest.mark.parametrize("refinement", sorted(REFINEMENT_REGISTRY))
def test_no_options_is_always_accepted(tiny_graph, refinement):
    """options를 넘기지 않는 기존 호출부(Local/VND/VNS 래퍼, 정제 없는 벤치마크 솔버)는
    정제 종류와 무관하게 그대로 통과해야 한다."""
    engine = WaypointEngine(inp=_inp(), G=tiny_graph, refinement=refinement)
    assert engine.refinement_options is None


@pytest.mark.parametrize("refinement", _IGNORES_OPTIONS)
def test_empty_options_is_treated_as_no_injection(tiny_graph, refinement):
    """빈 매핑은 주입으로 보지 않는다 — _alns_options_from_params()가 해당 키가 하나도
    없을 때 None을 돌려주는 것과 같은 취급이며, 빈 dict로도 막히면 호출부가 불필요하게
    조건문을 들고 있어야 한다."""
    engine = WaypointEngine(
        inp=_inp(), G=tiny_graph, refinement=refinement, refinement_options={},
    )
    assert not engine.refinement_options


# ── 반환 규약: 최종 경로 1개 + 후보 2개 (이슈 #443) ─────────────────────────
#
# 후보 선별 자체(_collect_alternatives)는 그래프 탐색과 무관한 순수 함수에 가까워서,
# 합성 Route로 직접 검증한다 — "후보가 모자라는 그래프"를 일부러 만들어 내는 것보다
# 훨씬 결정적이다. 실제 탐색을 거친 반환 개수는 아래 격자 테스트가 따로 확인한다.

_GRID = 7
_LAT_STEP = 0.0015   # 약 167m/step
_LON_STEP = 0.0018   # 약 160m/step (37.5도 위도 기준)
_ORIGIN_LAT, _ORIGIN_LON = 37.5000, 127.0000


def _grid_coords(row: int, col: int) -> tuple[float, float]:
    return _ORIGIN_LAT + row * _LAT_STEP, _ORIGIN_LON + col * _LON_STEP


@pytest.fixture
def grid_graph() -> nx.Graph:
    """7x7 격자(실제 위경도 간격). 엣지 length는 두 끝점의 Haversine 거리라 A*가
    의미 있게 동작한다 — test_grasp_waypoint.py의 5x5 격자와 같은 방식이다."""
    G = nx.Graph()
    for row in range(_GRID):
        for col in range(_GRID):
            lat, lon = _grid_coords(row, col)
            G.add_node(row * _GRID + col + 1, lat=lat, lon=lon)
    for row in range(_GRID):
        for col in range(_GRID):
            n = row * _GRID + col + 1
            for dr, dc in ((0, 1), (1, 0)):
                r2, c2 = row + dr, col + dc
                if r2 >= _GRID or c2 >= _GRID:
                    continue
                lat1, lon1 = _grid_coords(row, col)
                lat2, lon2 = _grid_coords(r2, c2)
                G.add_edge(n, r2 * _GRID + c2 + 1,
                           length=PathUtils._haversine_m(lat1, lon1, lat2, lon2))
    return G


def _grid_inp(target_km: float = 1.2) -> CircularRouteInput:
    """격자 중앙에서 출발하는 입력."""
    lat, lon = _grid_coords(_GRID // 2, _GRID // 2)
    return CircularRouteInput(start_lat=lat, start_lon=lon, target_km=target_km)


def _route(node_ids: list[int], repeated: float = 0.0) -> Route:
    """합성 Route. _collect_alternatives는 node_ids만 보므로 나머지 필드는 자리만 채운다."""
    return Route(node_ids=node_ids, waypoints=node_ids[1:2], distance_m=1000.0,
                 repeated_edge_ratio=repeated)


def _pool_entry(node_ids: list[int], error_m: float, repeated: float = 0.0) -> tuple:
    """(RouteObjective, Route) 한 쌍 — find_path()가 candidate_pool에 쌓는 형태 그대로."""
    return (
        RouteObjective(feasible=True, distance_error_m=error_m, repeated_edge_ratio=repeated),
        _route(node_ids, repeated),
    )


def _multi_engine(graph) -> WaypointEngine:
    """MULTI_CANDIDATE_COMBOS에 속하는 조합 하나로 엔진을 만든다."""
    construction, refinement = sorted(MULTI_CANDIDATE_COMBOS)[0]
    return WaypointEngine(inp=_inp(), G=graph, construction=construction, refinement=refinement)


def test_alternatives_exclude_the_final_route_and_keep_quality_order(tiny_graph):
    """후보는 최종 경로를 빼고 품질 순으로 채워진다."""
    engine = _multi_engine(tiny_graph)
    best = _route([1, 2, 1])
    pool = [
        (RouteObjective(feasible=True, distance_error_m=5.0, repeated_edge_ratio=0.0), best),
        _pool_entry([1, 2, 3, 1], error_m=50.0),
        _pool_entry([1, 3, 1], error_m=20.0),
        _pool_entry([1, 4, 1], error_m=80.0),
    ]
    alternatives = engine._collect_alternatives(pool, best)

    assert len(alternatives) == CANDIDATE_COUNT - 1
    assert [r.node_ids for r in alternatives] == [[1, 3, 1], [1, 2, 3, 1]]  # 오차 20 -> 50 순
    assert all(r.node_ids != best.node_ids for r in alternatives)


def test_duplicate_node_paths_are_dropped(tiny_graph):
    """노드열이 완전히 같은 후보는 한 번만 쓴다."""
    engine = _multi_engine(tiny_graph)
    best = _route([1, 2, 1])
    pool = [
        _pool_entry([1, 3, 1], error_m=20.0),
        _pool_entry([1, 3, 1], error_m=21.0),   # 같은 노드열
        _pool_entry([1, 4, 1], error_m=30.0),
    ]
    alternatives = engine._collect_alternatives(pool, best)

    assert [r.node_ids for r in alternatives] == [[1, 3, 1], [1, 4, 1]]


def test_shortfall_is_padded_with_the_final_route(tiny_graph):
    """서로 다른 후보가 모자라면 최종 경로를 복제해 항상 CANDIDATE_COUNT-1개를 채운다."""
    engine = _multi_engine(tiny_graph)
    best = _route([1, 2, 1])
    pool = [
        (RouteObjective(feasible=True, distance_error_m=5.0, repeated_edge_ratio=0.0), best),
        _pool_entry([1, 2, 1], error_m=7.0),  # 최종 경로와 같은 노드열뿐이라 쓸 후보가 없다
    ]
    alternatives = engine._collect_alternatives(pool, best)

    assert len(alternatives) == CANDIDATE_COUNT - 1
    assert all(r is best for r in alternatives)


def test_no_alternatives_without_a_final_route(tiny_graph):
    """경로 생성에 실패하면(best_route=None) 후보도 없다 — 실패 응답은 1개로 남는다."""
    engine = _multi_engine(tiny_graph)
    assert engine._collect_alternatives([_pool_entry([1, 3, 1], 20.0)], None) == []


@pytest.mark.parametrize("combo", sorted({("grasp", "vnd"), ("grasp", "vns"), ("beam", "local")}))
def test_single_candidate_combos_get_no_alternatives(tiny_graph, combo):
    """후보를 낼 원천이 없는 조합은 풀이 있어도 후보를 만들지 않는다."""
    construction, refinement = combo
    assert combo not in MULTI_CANDIDATE_COMBOS
    engine = WaypointEngine(
        inp=_inp(), G=tiny_graph, construction=construction, refinement=refinement,
    )
    best = _route([1, 2, 1])
    assert engine._collect_alternatives([_pool_entry([1, 3, 1], 20.0)], best) == []


@pytest.mark.parametrize("combo", sorted(MULTI_CANDIDATE_COMBOS))
def test_multi_candidate_combo_returns_exactly_three_responses(grid_graph, combo):
    """실제 탐색을 거쳐도 성공 응답은 항상 CANDIDATE_COUNT개이고, 첫 번째가 최종 경로다."""
    construction, refinement = combo
    engine = WaypointEngine(
        inp=_grid_inp(), G=grid_graph, construction=construction, refinement=refinement,
    )
    responses = engine.run()

    assert responses[0].status == WalkRouteStatus.SUCCESS, "격자에서 경로가 나와야 의미 있는 검증이 된다"
    assert len(responses) == CANDIDATE_COUNT
    assert len(engine.last_alternative_routes) == CANDIDATE_COUNT - 1
    assert responses[0].coordinates == engine._to_response(engine.last_route.node_ids).coordinates

    # 중복이 있다면 그건 패딩(최종 경로 복제)이어야 한다 — 다른 후보끼리 겹치면 안 된다.
    node_paths = [tuple(r.node_ids) for r in engine.last_alternative_routes]
    duplicates = [p for p in node_paths if node_paths.count(p) > 1 or p == tuple(engine.last_route.node_ids)]
    assert all(p == tuple(engine.last_route.node_ids) for p in duplicates)


def test_single_candidate_combo_returns_one_response(grid_graph):
    """후보를 안 내는 조합의 반환 개수는 이 변경 전과 같다."""
    engine = WaypointEngine(
        inp=_grid_inp(), G=grid_graph, construction="grasp", refinement="vnd",
    )
    responses = engine.run()

    assert len(responses) == 1
    assert engine.last_alternative_routes == []


def test_final_route_is_unchanged_by_candidate_collection(grid_graph, monkeypatch):
    """후보 수집이 최종 경로 선택에 끼어들지 않는다 — 같은 seed에서 후보를 내는 조합과
    내지 않는 조합의 find_path() 결과가 같아야 한다(정제가 같으므로).

    이 변경의 핵심 회귀 방지선이다. 벤치마크 CSV가 최종 경로 하나만 보므로, 후보 수집이
    승자 선택에 끼어들면 지표가 조용히 달라진다."""
    common = dict(inp=_grid_inp(), G=grid_graph, construction="grasp", refinement="local")
    multi = WaypointEngine(**common)
    start = PathUtils(grid_graph).find_nearest_node(multi.inp.start_lat, multi.inp.start_lon)
    with_candidates = multi.find_path(start, multi.inp.target_km)
    assert multi.last_alternative_routes, "후보를 내는 조합이어야 비교에 의미가 있다"

    # 같은 조합을 "후보를 안 내는" 상태로만 돌려 비교한다(monkeypatch가 자동 복원).
    monkeypatch.setattr(assembly, "MULTI_CANDIDATE_COMBOS", frozenset())
    solo = WaypointEngine(**common)
    solo_nodes = solo.find_path(start, solo.inp.target_km)

    assert with_candidates == solo_nodes
    assert solo.last_alternative_routes == []


# ── candidate_feature_vectors: 장기 프로필 SGD 스냅샷 ──────────────────────
#
# run()이 반환하는 각 응답과 같은 순서로 {"safety", "comfort"} 평균을 채운다.
# grid_graph는 safety_score/slope_score를 설정하지 않으므로
# scoring_engine._build_feature_cache()의 기본값(둘 다 데이터 없으면 0.0)이
# 그대로 나와야 한다 — 값 자체보다 "채워지는지·순서가 맞는지·새지 않는지"가 검증 대상이다.

_NO_FEATURE_DATA = {"safety": 0.0, "comfort": 0.0}


@pytest.mark.parametrize("combo", sorted(MULTI_CANDIDATE_COMBOS))
def test_candidate_feature_vectors_match_multi_candidate_responses(grid_graph, combo):
    """후보를 내는 조합은 응답 개수만큼 candidate_feature_vectors가 채워진다."""
    construction, refinement = combo
    engine = WaypointEngine(
        inp=_grid_inp(), G=grid_graph, construction=construction, refinement=refinement,
    )
    responses = engine.run()

    assert len(engine.candidate_feature_vectors) == len(responses) == CANDIDATE_COUNT
    assert all(vec == _NO_FEATURE_DATA for vec in engine.candidate_feature_vectors)


def test_candidate_feature_vectors_single_candidate_combo(grid_graph):
    """후보를 안 내는 조합은 최종 경로 1개짜리 벡터만 남는다."""
    engine = WaypointEngine(
        inp=_grid_inp(), G=grid_graph, construction="grasp", refinement="vnd",
    )
    responses = engine.run()

    assert len(engine.candidate_feature_vectors) == len(responses) == 1
    assert engine.candidate_feature_vectors[0] == _NO_FEATURE_DATA


def test_candidate_feature_vectors_do_not_leak_across_runs(grid_graph):
    """같은 엔진 인스턴스로 run()을 두 번 불러도 이전 호출의 값이 누적되지 않는다."""
    engine = WaypointEngine(
        inp=_grid_inp(), G=grid_graph, construction="grasp", refinement="alns",
    )
    first = engine.run()
    second = engine.run()

    assert len(engine.candidate_feature_vectors) == len(second) == len(first) == CANDIDATE_COUNT


# ── 편도(oneway) 통합 — mock 없이 실제 그래프·실제 엔진 실행(2026-09-20, #498 확장) ──
#
# OnewayRouteInput(end_lat/end_lon 보유)을 넘기면 WaypointEngine이 자동으로 편도로
# 판별해 construction/refinement 전부에 end_node를 흘린다(모듈 docstring 참고). 아래는
# grasp/beam × 5개 정제 조합 전부가 실제로 목적지에서 끝나는지, 그리고 CircularRouteInput
# 경로(end_node=None)가 이 변경으로 전혀 달라지지 않는지 확인한다.

_ONEWAY_START = (0, 0)
_ONEWAY_END = (_GRID - 1, _GRID - 1)


def _oneway_inp() -> OnewayRouteInput:
    start_lat, start_lon = _grid_coords(*_ONEWAY_START)
    end_lat, end_lon = _grid_coords(*_ONEWAY_END)
    direct_m = PathUtils._haversine_m(start_lat, start_lon, end_lat, end_lon)
    return OnewayRouteInput(
        start_lat=start_lat, start_lon=start_lon, end_lat=end_lat, end_lon=end_lon,
        target_km=direct_m * 1.5 / 1000,
    )


@pytest.mark.parametrize("construction", ["grasp", "beam"])
@pytest.mark.parametrize("refinement", sorted(REFINEMENT_REGISTRY))
def test_oneway_input_produces_route_ending_at_destination(grid_graph, construction, refinement):
    """construction×refinement 10개 조합 전부, mock 없이 실제 그래프에서 실행해 반환
    노드열이 실제로 도착지(end_node)에서 끝나는지 확인한다."""
    engine = WaypointEngine(
        inp=_oneway_inp(), G=grid_graph, construction=construction, refinement=refinement,
    )
    responses = engine.run()

    assert responses[0].status == WalkRouteStatus.SUCCESS
    assert responses[0].mode == WalkMode.ONEWAY_RANDOM
    end_node = _ONEWAY_END[0] * _GRID + _ONEWAY_END[1] + 1  # grid_graph의 노드 id 공식과 동일
    assert engine.last_route is not None
    assert engine.last_route.node_ids[0] == 1  # (0,0)
    assert engine.last_route.node_ids[-1] == end_node
    assert engine.last_route.node_ids[-1] != 1  # 순환으로 퇴화하지 않았다


def test_oneway_missing_end_node_reports_no_nearest_end_node(grid_graph, monkeypatch):
    """도착 노드를 못 찾으면(find_nearest_node가 None) NO_NEAREST_END_NODE로 실패해야
    한다 — 조용히 순환으로 되돌아가면 안 된다. find_nearest_node(max_dist_m 없이 호출)는
    실제로는 빈 그래프에서만 None을 주므로(PathUtils.find_nearest_node docstring),
    출발 노드는 정상 조회되는 상황을 monkeypatch로 재현한다."""
    engine = WaypointEngine(inp=_oneway_inp(), G=grid_graph, construction="grasp", refinement="alns")

    real_find_nearest_node = PathUtils.find_nearest_node
    calls = 0

    def fake_find_nearest_node(self, lat, lon, max_dist_m=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_find_nearest_node(self, lat, lon, max_dist_m)
        return None  # 두 번째 호출(도착 노드 조회)만 실패시킨다

    monkeypatch.setattr(PathUtils, "find_nearest_node", fake_find_nearest_node)
    responses = engine.run()

    assert responses[0].status == WalkRouteStatus.NO_NEAREST_END_NODE
    assert responses[0].mode == WalkMode.ONEWAY_RANDOM


def test_circular_input_is_unaffected_by_oneway_support(grid_graph):
    """CircularRouteInput(end_lat 없음)로 만든 엔진은 이번 변경 이후에도 end_node=None
    경로 그대로 순환으로 동작한다 — walk_mode 자동 판별이 편도를 오검출하지 않는지가
    핵심이다."""
    engine = WaypointEngine(
        inp=_grid_inp(), G=grid_graph, construction="grasp", refinement="alns",
    )
    responses = engine.run()

    assert responses[0].status == WalkRouteStatus.SUCCESS
    assert responses[0].mode == WalkMode.CIRCULAR_RANDOM
    assert engine.last_route.node_ids[0] == engine.last_route.node_ids[-1]  # 순환은 그대로 복귀
