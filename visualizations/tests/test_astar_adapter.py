"""A*·ALT 어댑터가 실제 실행을 그대로 재생하는지 확인한다.

핵심 질문은 하나다 — "화면에 보이는 단계가 엔진이 실제로 한 일과 같은가". 그래서
동점이 많은 격자와 동점이 없는 격자 양쪽에서 재생 경로가 엔진 반환 경로와 노드열까지
같은지 보고, 어긋나면 예외로 멈추는지도 확인한다.
"""

import copy
import sys

import networkx as nx
import pytest

from src.route_engine.engines.oneway_astar import OnewayAstarEngine
from src.schema.route_schema import OnewayRouteInput
from visualizations.astar_adapter import FRONTIER_TOP, TraceMismatchError, record_astar_run
from visualizations.route_experiment import (
    DEFAULT_ALT_K,
    DEFAULT_ALT_METHOD,
    DEFAULT_ALT_SEED,
    compare_recording,
    execute,
    graph_digest,
    prepare_alt,
)

START, END = 0, 24


def _engine(graph, *, heuristic="haversine", alt_k=4):
    """execute()와 같은 방식으로 깊은 복사본 위에 엔진을 세운다."""
    local = copy.deepcopy(graph)
    if heuristic == "alt":
        prepare_alt(local, method="planar", k=alt_k, seed=0)
    inp = OnewayRouteInput(start_lat=local.nodes[START]["lat"], start_lon=local.nodes[START]["lon"],
                           end_lat=local.nodes[END]["lat"], end_lon=local.nodes[END]["lon"])
    return OnewayAstarEngine(inp, local), local


def _record(graph, *, heuristic="haversine", alt_k=4, mode="shortest"):
    engine, local = _engine(graph, heuristic=heuristic, alt_k=alt_k)
    return engine, record_astar_run(engine, local, mode=mode, alt_seed=0)


def _selects(recording):
    return [event for event in recording["events"] if event["kind"] == "select"]


def test_varied_grid_really_has_no_tied_edge_lengths(varied_grid):
    lengths = [data["length"] for _, _, data in varied_grid.edges(data=True)]
    assert len(set(lengths)) == varied_grid.number_of_edges()
    assert min(lengths) > 120  # 좌표 간격(위도 0.001도 ≈ 111m)보다 길어야 Haversine이 admissible


@pytest.mark.parametrize("fixture", ["grid", "varied_grid"])
@pytest.mark.parametrize("heuristic", ["haversine", "alt"])
def test_replay_matches_the_real_engine_path_node_by_node(request, fixture, heuristic):
    graph = request.getfixturevalue(fixture)
    before = graph_digest(graph)
    engine, recording = _record(graph, heuristic=heuristic)

    events = recording["events"]
    assert len(_selects(recording)) == recording["popped"]
    assert len(events) == recording["popped"] + 2  # run_start + pop마다 1개 + final
    assert events[0]["kind"] == "run_start"
    assert events[-1]["paths"][0] == engine.last_path_nodes
    assert recording["paths"] == [engine.last_path_nodes]
    assert events[-1]["values"]["popped"] == recording["popped"]
    # 동점이 있어도(모든 간선 120m) 재생이 같은 경로를 낸다 — 예외 없이 여기까지 온다.
    distance = sum(graph[u][v]["length"]
                   for u, v in zip(engine.last_path_nodes, engine.last_path_nodes[1:]))
    assert distance == pytest.approx(nx.dijkstra_path_length(graph, START, END, weight="length"))
    assert graph_digest(graph) == before
    assert sys.gettrace() is None


@pytest.mark.parametrize("fixture", ["grid", "varied_grid"])
def test_alt_events_decompose_the_heuristic_and_stay_admissible(request, fixture):
    graph = request.getfixturevalue(fixture)
    _, recording = _record(graph, heuristic="alt", alt_k=4)
    for event in _selects(recording):
        values = event["values"]
        assert values["h_kind"] == "alt"
        terms = values["h_terms"]
        assert terms, "ALT 실행에는 랜드마크 항이 있어야 합니다."
        assert max(term["bound_m"] for term in terms) == pytest.approx(values["h_m"], abs=1e-9)
        assert values["best_landmark"] in [term["landmark"] for term in terms]
        remaining = nx.dijkstra_path_length(graph, event["current"], END, weight="length")
        assert values["h_m"] <= remaining + 1e-6


def test_haversine_events_have_no_landmark_terms(grid):
    _, recording = _record(grid)
    for event in _selects(recording):
        assert event["values"]["h_kind"] == "haversine"
        assert "h_terms" not in event["values"]
        assert "best_landmark" not in event["values"]


@pytest.mark.parametrize("heuristic", ["haversine", "alt"])
def test_frontier_top_is_sorted_by_f_and_bounded(grid, heuristic):
    _, recording = _record(grid, heuristic=heuristic)
    for event in _selects(recording):
        top = event["values"]["frontier_top"]
        assert len(top) <= FRONTIER_TOP
        assert [item["f_m"] for item in top] == sorted(item["f_m"] for item in top)
        assert {item["node"] for item in top} <= set(event["frontier"])
        for item in top:
            assert item["f_m"] == pytest.approx(item["g_m"] + item["h_m"])


def test_expanded_neighbours_are_grouped_into_the_pop_that_produced_them(grid):
    _, recording = _record(grid)
    pushed = 0
    for event in _selects(recording):
        for entry in event["values"]["expanded"]:
            assert entry["result"] in ("pushed_new", "pushed_improved", "skipped")
            assert entry["reason"] in ("new", "improved", "worse", "blocked", "cutoff")
            pushed += entry["result"] != "skipped"
    # 시작 노드를 큐에 올리는 최초 1회는 훅 없이 큐를 만들 때 세므로 기록에 없다.
    assert pushed == recording["pushed"] - 1


def test_replaced_engine_path_stops_the_recording(grid):
    engine, local = _engine(grid)
    original_run = engine.run

    def run_then_replace():
        responses = original_run()
        engine.last_path_nodes = list(reversed(engine.last_path_nodes))
        return responses

    engine.run = run_then_replace
    with pytest.raises(TraceMismatchError, match="엔진 반환 경로와 다릅니다"):
        record_astar_run(engine, local, mode="shortest")


def test_missing_active_heuristic_reports_a_contract_change(grid):
    engine, local = _engine(grid)
    del engine._active_heuristic
    with pytest.raises(RuntimeError, match="엔진 계약이 바뀌었습니다"):
        record_astar_run(engine, local, mode="shortest")


def test_execute_with_alt_preserves_the_result_and_records_conditions(grid):
    before = graph_digest(grid)
    start, end = {"node": START, **grid.nodes[START]}, {"node": END, **grid.nodes[END]}
    options = {"heuristic": "alt", "alt_k": 4}
    recorded = execute(grid, "shortest", start, end, **options)
    plain = execute(grid, "shortest", start, end, record=False, **options)

    assert compare_recording(recorded, plain)
    assert graph_digest(grid) == before
    assert sys.gettrace() is None
    assert recorded["alt_prepare_seconds"] > 0
    assert plain["alt_prepare_seconds"] > 0
    heuristic = recorded["conditions"]["heuristic"]
    assert heuristic["name"] == "alt_planar"
    assert heuristic["k_requested"] == 4
    assert len(heuristic["landmarks"]) == heuristic["k_actual"]
    assert recorded["metrics"][0]["distance_m"] == nx.dijkstra_path_length(grid, START, END, weight="length")


def test_both_heuristics_return_the_same_distance(grid):
    start, end = {"node": START, **grid.nodes[START]}, {"node": END, **grid.nodes[END]}
    haversine = execute(grid, "shortest", start, end)
    alt = execute(grid, "shortest_alt", start, end, heuristic="alt", alt_k=4)
    # 둘 다 admissible하므로 최적 거리는 같다. 동점 처리 때문에 노드열은 다를 수 있다.
    assert haversine["metrics"][0]["distance_m"] == pytest.approx(alt["metrics"][0]["distance_m"])
    assert alt["conditions"]["mode"] == "shortest_alt"


def test_visualization_alt_defaults_match_the_service_settings():
    from src.config.settings import Settings

    fields = Settings.model_fields
    assert DEFAULT_ALT_METHOD == fields["WALK_ALT_METHOD"].default
    assert DEFAULT_ALT_K == fields["WALK_ALT_K"].default
    assert DEFAULT_ALT_SEED == fields["WALK_ALT_SEED"].default


def test_unknown_heuristic_name_is_rejected(grid):
    start, end = {"node": START, **grid.nodes[START]}, {"node": END, **grid.nodes[END]}
    with pytest.raises(ValueError, match="heuristic"):
        execute(grid, "shortest", start, end, heuristic="euclidean")
