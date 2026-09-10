import networkx as nx
import pytest

from src.route_engine.engines.grasp_waypoint_common import RouteObjective
from visualizations.route_story import path_metrics, select_keyframes
from visualizations.waypoint_trace import objective_decision


def test_repeated_edges_count_reverse_traversal_and_partial_has_no_target_error():
    graph = nx.Graph()
    graph.add_edge(1, 2, length=100)
    graph.add_edge(2, 3, length=50)
    complete = path_metrics(graph, [1, 2, 3, 2, 1], 300, .05, 1, 1)
    assert complete["distance_m"] == 300
    assert complete["repeated_edge_ratio"] == .5
    assert complete["target_within_tolerance"]
    partial = path_metrics(graph, [1, 2], 300, .05, 1, 1)
    assert partial["target_error_m"] is None
    assert not partial["complete"]
    assert path_metrics(graph, [1, 3], 300, .05, 1, 1) is None


@pytest.mark.parametrize("candidate,baseline,accepted,reason", [
    ((True, 140, .5), (False, 151, .0), True, "충족 여부"),
    ((True, 140, .1), (True, 10, .2), True, "재통행 비율, 거리 오차"),
    ((False, 200, .5), (False, 300, .0), True, "거리 오차, 재통행"),
    ((True, 10, .2), (True, 10, .2), False, "평가값이 같아"),
])
def test_explanations_match_real_objective_order(candidate, baseline, accepted, reason):
    details = objective_decision(RouteObjective(*candidate), RouteObjective(*baseline))
    assert details["accepted"] is accepted
    assert reason in details["decision_reason"]


def test_keyframes_bound_preserves_stages_and_final_without_mutating_raw_events():
    events = [{"phase": "start"}, {"phase": "constructed"}]
    events += [{"phase": "neighbor"} for _ in range(200)]
    events += [{"phase": "improved", "before_metrics": {"distance_m": 2000},
                "stage_metrics": {"distance_m": 2100+i}} for i in range(40)]
    events += [{"phase": "vns_decision", "accepted": False},
               {"phase": "prune"}, {"phase": "final"}]
    indexes = select_keyframes(events)
    assert len(indexes) <= 26
    assert indexes == sorted(set(indexes))
    assert indexes[0] == 0 and indexes[-1] == len(events)-1
    assert {events[i]["phase"] for i in indexes} == {e["phase"] for e in events}
    assert len(events) == 245


def test_astar_keyframes_keep_first_geographic_progress_crossings():
    events = [{"phase": "start"}] + [{"phase": "astar", "goal_progress": p}
        for p in (0, .1, .3, .2, .55, .8, 1)] + [{"phase": "final"}]
    selected = select_keyframes(events)
    assert {3, 5, 6} <= set(selected)
