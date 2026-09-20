"""
tests/unit/test_oneway_grasp_waypoint_alns.py

oneway_grasp_waypoint_alns.py::OnewayGraspWaypointAlnsEngine에 대한 단위 테스트
(2026-09-20, #498 확장 — "편도 우회 정제·서비스 연결" 이슈). 이 클래스는
circular_grasp_waypoint_alns.py::CircularGraspWaypointAlnsEngine과 거의 동일한 얇은
래퍼이므로(입력 스키마만 다름), WaypointEngine 자체의 일반 동작(정제 조합, 후보 3개
반환, candidate_feature_vectors 등)은 test_waypoint_engine_assembly.py/
test_grasp_waypoint_alns.py가 이미 검증한다 — 여기서는 "OnewayRouteInput을 받아
편도로 자동 판별되고, GRASP_ALNS_CONFIG/GRASP_ALNS_OPTIONS 튜닝값을 그대로 쓰며,
실제로 목적지에서 끝나는가"만 이 클래스 고유의 관심사로 검증한다.
"""

import networkx as nx
import pytest

from src.interfaces.schema.walk_schema import WalkMode, WalkRouteStatus
from src.route_engine.engines.circular_grasp_waypoint_alns import GRASP_ALNS_CONFIG, GRASP_ALNS_OPTIONS
from src.route_engine.engines.oneway_grasp_waypoint_alns import OnewayGraspWaypointAlnsEngine
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.engines.waypoint_engine_assembly import CANDIDATE_COUNT
from src.route_engine.engines.grasp_waypoint_common import SelectionStatus
from src.schema.route_schema import OnewayRouteInput

_LAT_STEP = 0.0015
_LON_STEP = 0.0018
_ORIGIN_LAT = 37.5000
_ORIGIN_LON = 127.0000


def _node_id(row: int, col: int) -> int:
    return row * 5 + col + 1


def _coords(row: int, col: int) -> tuple[float, float]:
    return _ORIGIN_LAT + row * _LAT_STEP, _ORIGIN_LON + col * _LON_STEP


@pytest.fixture
def grid_graph() -> nx.Graph:
    """5x5 격자 그래프 — test_grasp_waypoint_alns.py::grid_graph와 동일 구성(이 저장소의
    기존 관례: 파일마다 자체 fixture를 둔다)."""
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


def _oneway_inp(target_ratio: float = 1.5) -> OnewayRouteInput:
    start_lat, start_lon = _coords(0, 0)
    end_lat, end_lon = _coords(4, 4)
    direct_m = PathUtils._haversine_m(start_lat, start_lon, end_lat, end_lon)
    return OnewayRouteInput(
        start_lat=start_lat, start_lon=start_lon, end_lat=end_lat, end_lon=end_lon,
        target_km=direct_m * target_ratio / 1000,
    )


def test_engine_uses_grasp_alns_tuning_defaults(grid_graph):
    """생성자 기본값이 순환판과 동일한 튜닝 확정값(GRASP_ALNS_CONFIG/GRASP_ALNS_OPTIONS)을
    쓰는지 확인한다 — 별도로 재튜닝하지 않았다는 계약."""
    engine = OnewayGraspWaypointAlnsEngine(inp=_oneway_inp(), G=grid_graph)
    assert engine.config == GRASP_ALNS_CONFIG
    assert engine.refinement_options == dict(GRASP_ALNS_OPTIONS)
    assert engine.construction == "grasp"
    assert engine.refinement == "alns"


def test_engine_returns_real_route_ending_at_destination(grid_graph):
    """mock 없이 실제 그래프에서 실행해, 반환 경로가 퇴화([start_node])하지 않고 실제로
    목적지 노드에서 끝나는지 확인한다."""
    engine = OnewayGraspWaypointAlnsEngine(inp=_oneway_inp(), G=grid_graph, seed=42)
    start_node, end_node = _node_id(0, 0), _node_id(4, 4)

    nodes = engine.find_path(start_node, target_km=_oneway_inp().target_km, end_node=end_node)
    assert nodes[0] == start_node
    assert nodes[-1] == end_node
    assert len(nodes) > 2  # 퇴화한 [start_node] 폴백이 아니라 실제 경유지를 거쳤다


def test_engine_sets_last_route_and_selection_status(grid_graph):
    engine = OnewayGraspWaypointAlnsEngine(inp=_oneway_inp(), G=grid_graph, seed=42)
    responses = engine.run()

    assert responses[0].status == WalkRouteStatus.SUCCESS
    assert responses[0].mode == WalkMode.ONEWAY_RANDOM
    assert engine.last_selection_status in (SelectionStatus.FEASIBLE, SelectionStatus.FALLBACK_DISTANCE)
    assert engine.last_route is not None


def test_engine_returns_three_candidates_like_circular_alns(grid_graph):
    """(grasp, alns)는 MULTI_CANDIDATE_COMBOS에 속하므로 순환판과 동일하게 최종 경로 1개
    + 후보 2개(총 CANDIDATE_COUNT개)를 반환해야 한다."""
    engine = OnewayGraspWaypointAlnsEngine(inp=_oneway_inp(), G=grid_graph, seed=42)
    responses = engine.run()

    assert len(responses) == CANDIDATE_COUNT
    assert len(engine.candidate_feature_vectors) == CANDIDATE_COUNT
