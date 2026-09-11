"""
tests/unit/test_waypoint_engine_assembly.py

waypoint_engine_assembly.py::WaypointEngine의 생성자 검증만 확인한다. 조합별 실제 경로
탐색 결과는 test_grasp_waypoint.py / test_grasp_waypoint_alns.py가 이미 검증하므로 여기서
반복하지 않는다(파일마다 자체 fixture를 두는 이 저장소의 기존 관례를 따른다).
"""

import networkx as nx
import pytest

from src.route_engine.engines.waypoint_engine_assembly import WaypointEngine
from src.route_engine.engines.waypoint_refinement import (
    OPTIONS_AWARE_REFINEMENTS,
    REFINEMENT_REGISTRY,
)
from src.schema.route_schema import CircularRouteInput

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
