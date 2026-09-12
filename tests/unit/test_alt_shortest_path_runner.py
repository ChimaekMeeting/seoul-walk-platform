"""점대점 벤치마크 러너(alt_shortest_path)와 계측 A*의 단위 검증.

실제 artifact(16만 노드)를 쓰지 않고 toy 그래프로만 돌린다. 장벽 grid는 "강 하나에
다리 하나" 모형이다 — 세로 장벽이 격자를 좌우로 가르고 한 행만 뚫려 있어, 직선거리는
가까운데 실제로는 다리까지 우회해야 하는 상황을 만든다. Haversine 휴리스틱이 약해지는
구간(시나리오 데이터셋의 detour tier)을 재현하기 위한 것이다.
"""

import networkx as nx
import pytest

from benchmarks.build_shortest_path_scenarios import (
    TIER_RULES,
    detour_ratio,
    qualifies,
)
from benchmarks.runner._astar_instrumented import astar_path_instrumented
from benchmarks.runner.alt_shortest_path import (
    CSV_COLUMNS,
    build_summary,
    haversine_heuristic,
    iter_configs,
    path_is_valid,
    prepare_config,
    run_scenario,
)
from benchmarks.runner.test_oneway_shortest_path import distance_weight

_BASE_LAT, _BASE_LON = 37.50, 127.00
# 좌표 간격(도)을 간선 길이(m)보다 훨씬 작게 잡아 Haversine <= 도로거리를 보장한다
# (route_engine/README.md의 admissibility 전제 절과 같은 toy 그래프 규약).
_COORD_STEP = 0.00005
_EDGE_M = 100.0


def _barrier_grid(rows=10, cols=10, barrier_col=5, gate_row=0):
    """세로 장벽이 있고 한 행(gate_row)만 뚫린 10x10 grid — 강과 다리 모형.

    barrier_col-1 열과 barrier_col 열 사이의 가로 간선을 gate_row만 남기고 지운다.
    좌/우를 오가려면 gate_row까지 올라갔다 내려와야 한다.
    """
    G = nx.Graph()
    for r in range(rows):
        for c in range(cols):
            node = r * cols + c
            G.add_node(
                node, lat=_BASE_LAT + r * _COORD_STEP, lon=_BASE_LON + c * _COORD_STEP
            )
    for r in range(rows):
        for c in range(cols):
            node = r * cols + c
            if c + 1 < cols:
                crosses_barrier = c + 1 == barrier_col
                if not crosses_barrier or r == gate_row:
                    G.add_edge(node, node + 1, length=_EDGE_M)
            if r + 1 < rows:
                G.add_edge(node, node + cols, length=_EDGE_M)
    return G


def _scenario(sid, tier, graph, start, end, dijkstra_m):
    def rec(node):
        data = graph.nodes[node]
        return {"node_id": node, "lat": data["lat"], "lon": data["lon"]}

    return {
        "id": sid,
        "tier": tier,
        "start": rec(start),
        "end": rec(end),
        "straight_m": 0.0,
        "dijkstra_m": dijkstra_m,
    }


# ────────────────────────────────────────────────
# 1. 계측 A*가 원본과 같은 동작인지
# ────────────────────────────────────────────────


def test_instrumented_astar_matches_networkx_and_counts_pops():
    G = _barrier_grid()
    heuristic = haversine_heuristic(G)
    start, end = 99, 0

    path, popped, pushed = astar_path_instrumented(
        G, start, end, heuristic=heuristic, weight=distance_weight
    )
    expected = nx.astar_path(G, start, end, heuristic=heuristic, weight=distance_weight)

    assert path == expected
    assert popped >= 1
    assert pushed >= 1


def test_instrumented_astar_raises_no_path_with_counters_attached():
    G = _barrier_grid()
    G.add_node(999, lat=_BASE_LAT, lon=_BASE_LON)  # 어디에도 붙지 않은 고립 노드

    with pytest.raises(nx.NetworkXNoPath) as excinfo:
        astar_path_instrumented(G, 0, 999, weight=distance_weight)

    # 예외 종류는 원본과 같고, 실패한 탐색의 계산량은 예외에 실려 온다.
    assert excinfo.value.popped >= 1
    assert excinfo.value.pushed >= 1


def test_instrumented_astar_with_zero_heuristic_pops_at_least_as_much_as_haversine():
    G = _barrier_grid()
    _, popped_zero, _ = astar_path_instrumented(G, 99, 0, weight=distance_weight)
    _, popped_hav, _ = astar_path_instrumented(
        G, 99, 0, heuristic=haversine_heuristic(G), weight=distance_weight
    )
    assert popped_zero >= popped_hav


# ────────────────────────────────────────────────
# 2. 러너가 6개 방식을 같은 기준으로 재는지
# ────────────────────────────────────────────────


def _run_all_methods(graph, scenarios, k=4, seed=0, repeats=1):
    pairs = [(sc["start"]["node_id"], sc["end"]["node_id"]) for sc in scenarios]
    baseline = {sc["id"]: sc["dijkstra_m"] for sc in scenarios}
    rows = []
    configs = [
        {"method": "dijkstra", "k": None, "seed": None},
        {"method": "haversine", "k": None, "seed": None},
        {"method": "random", "k": k, "seed": seed},
        {"method": "farthest", "k": k, "seed": seed},
        {"method": "planar", "k": k, "seed": None},
        {"method": "avoid", "k": k, "seed": seed},
    ]
    for config in configs:
        prepared = prepare_config(config, graph, distance_weight, pairs)
        for scenario in scenarios:
            rows.append(
                run_scenario(
                    graph, scenario, config, prepared, distance_weight, repeats, baseline
                )
            )
    return rows


def test_all_six_methods_match_dijkstra_cost_and_return_valid_paths():
    G = _barrier_grid()
    start, end = 99, 0
    dijkstra_m = nx.shortest_path_length(G, start, end, weight=distance_weight)
    scenarios = [_scenario("barrier-1", "detour", G, start, end, dijkstra_m)]

    rows = _run_all_methods(G, scenarios)

    assert {row["method"] for row in rows} == {
        "dijkstra",
        "haversine",
        "random",
        "farthest",
        "planar",
        "avoid",
    }
    for row in rows:
        assert row["status"] == "ok", row
        assert row["cost_match"], row
        assert row["path_valid"], row
        assert row["popped"] >= 1


def test_result_rows_carry_every_declared_csv_column():
    G = _barrier_grid()
    dijkstra_m = nx.shortest_path_length(G, 99, 0, weight=distance_weight)
    rows = _run_all_methods(G, [_scenario("barrier-1", "detour", G, 99, 0, dijkstra_m)])

    for row in rows:
        assert set(row) == set(CSV_COLUMNS)


def test_same_scenario_costs_zero_and_expands_at_most_one_node():
    G = _barrier_grid()
    scenarios = [_scenario("same-1", "same", G, 42, 42, 0.0)]

    rows = _run_all_methods(G, scenarios)

    for row in rows:
        assert row["status"] == "ok", row
        assert row["path_m"] == 0.0, row
        assert row["popped"] <= 1, row


def test_unreachable_scenario_is_recorded_as_no_path_without_raising():
    G = _barrier_grid()
    G.add_node(999, lat=_BASE_LAT, lon=_BASE_LON)  # 다른 연결요소(고립 노드)
    scenarios = [_scenario("unreachable-1", "unreachable", G, 0, 999, None)]

    rows = _run_all_methods(G, scenarios)

    for row in rows:
        assert row["status"] == "no_path", row
        assert row["path_m"] is None, row
        assert row["cost_match"], row  # 기준선도 경로 없음 -> 결론 일치
        assert row["popped"] >= 1, row  # 실패한 탐색의 계산량도 기록된다
        assert row["search_median_s"] >= 0.0


def test_alt_does_not_expand_more_nodes_than_haversine_on_the_barrier_grid():
    """방향성만 확인한다 — 구체적 popped 값은 그래프·구현에 따라 달라지므로 고정하지 않는다."""
    G = _barrier_grid()
    start, end = 99, 0
    dijkstra_m = nx.shortest_path_length(G, start, end, weight=distance_weight)
    scenarios = [_scenario("barrier-1", "detour", G, start, end, dijkstra_m)]

    rows = _run_all_methods(G, scenarios, k=4, seed=0)
    popped = {row["method"]: row["popped"] for row in rows}

    assert popped["farthest"] <= popped["haversine"]
    assert popped["haversine"] <= popped["dijkstra"]


def test_iter_configs_covers_every_method_and_skips_seeds_for_planar():
    configs = iter_configs([4, 8], [0, 1])

    assert configs[0]["method"] == "dijkstra"
    assert configs[1]["method"] == "haversine"
    planar = [c for c in configs if c["method"] == "planar"]
    assert len(planar) == 2  # k마다 1회, seed 없음
    assert all(c["seed"] is None for c in planar)
    for method in ("random", "farthest", "avoid"):
        assert len([c for c in configs if c["method"] == method]) == 4  # k 2개 x seed 2개


def test_build_summary_groups_by_tier_and_method():
    G = _barrier_grid()
    dijkstra_m = nx.shortest_path_length(G, 99, 0, weight=distance_weight)
    rows = _run_all_methods(G, [_scenario("barrier-1", "detour", G, 99, 0, dijkstra_m)])

    summary = build_summary(rows, configs=[])

    keys = {(e["tier"], e["method"]) for e in summary["by_tier_method"]}
    assert ("detour", "dijkstra") in keys
    assert ("detour", "avoid") in keys
    assert all(e["cost_match_ratio"] == 1.0 for e in summary["by_tier_method"])


def test_path_is_valid_rejects_broken_and_misrouted_paths():
    G = _barrier_grid()
    good = nx.shortest_path(G, 0, 9, weight=distance_weight)

    assert path_is_valid(G, good, 0, 9)
    assert not path_is_valid(G, good, 0, 8)  # 끝점 불일치
    assert not path_is_valid(G, [0, 99], 0, 99)  # 간선으로 이어져 있지 않음
    assert not path_is_valid(G, [], 0, 9)


# ────────────────────────────────────────────────
# 3. 시나리오 생성기의 tier 판정
# ────────────────────────────────────────────────


def test_detour_ratio_is_none_when_straight_distance_is_zero():
    assert detour_ratio(0.0, 100.0) is None
    assert detour_ratio(-1.0, 100.0) is None
    assert detour_ratio(1000.0, 1600.0) == pytest.approx(1.6)


@pytest.mark.parametrize(
    "tier,straight_m,road_m,expected",
    [
        ("near", 500.0, 600.0, True),  # 하한 경계 포함
        ("near", 1500.0, 1600.0, True),  # 상한 경계 포함
        ("near", 499.9, 600.0, False),
        ("near", 1500.1, 1600.0, False),
        ("mid", 4000.0, 4500.0, True),
        ("mid", 1000.0, 1200.0, False),
        ("long", 8000.0, 9000.0, True),
        ("long", 12000.1, 13000.0, False),
        ("detour", 2000.0, 3200.0, True),  # 비율 1.6 경계 포함
        ("detour", 2000.0, 3199.0, False),  # 비율 1.5995 -> 탈락
        ("detour", 500.0, 2000.0, False),  # 비율은 되지만 직선거리 범위 밖
    ],
)
def test_qualifies_applies_straight_distance_and_detour_ratio_rules(
    tier, straight_m, road_m, expected
):
    assert qualifies(tier, straight_m, road_m) is expected


def test_qualifies_rejects_unreachable_pairs_and_unknown_tiers():
    assert qualifies("near", 1000.0, None) is False
    with pytest.raises(KeyError):
        qualifies("same", 1000.0, 1200.0)


def test_tier_rules_declare_the_counts_the_dataset_promises():
    assert {tier: rule["count"] for tier, rule in TIER_RULES.items()} == {
        "near": 4,
        "mid": 4,
        "long": 4,
        "detour": 4,
    }
