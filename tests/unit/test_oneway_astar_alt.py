"""ALT 휴리스틱을 주입해도 OnewayAstarEngine의 응답 계약이 그대로인지 확인한다.

ALT와 Haversine은 둘 다 admissible하므로 A*가 찾는 **최적 비용**은 항상 같다. 다만
최단경로가 여럿이면(동점) 어느 것을 고르는지는 휴리스틱에 따라 달라질 수 있다 —
2026-09-12 확인: 간선 길이가 전부 100m로 같은 grid에서는 두 휴리스틱이 비용은 같고
노드열이 다른 경로를 냈고, 간선 길이를 서로 다르게 바꿔 동점을 없애면 노드열까지
완전히 같아졌다. 그래서 이 파일은 "비용·status는 항상 같다"와 "동점이 없으면 경로도
같다"를 나눠서 확인한다.

장벽 grid(강·다리 모형)는 tests/unit/test_alt_shortest_path_runner.py와 같은 구조다 —
직선거리는 가까운데 실제로는 다리까지 우회해야 해서 Haversine 휴리스틱이 약해지는,
ALT와 차이가 가장 잘 드러나는 형태다.
"""

import logging

import networkx as nx
import pytest

from src.interfaces.schema.walk_schema import WalkRouteStatus
from src.route_engine.alt_runtime import attach_alt_heuristic, prepare_alt_heuristic
from src.route_engine.engines.oneway_astar import OnewayAstarEngine
from src.schema.route_schema import OnewayRouteInput

_BASE_LAT, _BASE_LON = 37.50, 127.00
_COORD_STEP = 0.00005
_EDGE_M = 100.0


def _barrier_grid(rows=10, cols=10, barrier_col=5, gate_row=0):
    """세로 장벽이 있고 한 행(gate_row)만 뚫린 grid — 강과 다리 모형."""
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
                if c + 1 != barrier_col or r == gate_row:
                    G.add_edge(node, node + 1, length=_EDGE_M)
            if r + 1 < rows:
                G.add_edge(node, node + cols, length=_EDGE_M)
    return G


def _route_input(G, start_node, end_node):
    s, e = G.nodes[start_node], G.nodes[end_node]
    return OnewayRouteInput(
        start_lat=s["lat"], start_lon=s["lon"], end_lat=e["lat"], end_lon=e["lon"]
    )


def _coords(response):
    return [tuple(c) if isinstance(c, (list, tuple)) else c for c in response.coordinates]


def _tie_free_grid():
    """간선 길이를 서로 다르게 줘 최단경로가 유일해지는 grid.

    길이가 전부 같으면 최적 경로가 여럿이라 휴리스틱마다 다른 것을 고를 수 있다.
    "휴리스틱을 바꿔도 경로가 같다"는 동점이 없을 때만 성립하는 성질이다.
    """
    G = _barrier_grid()
    for i, (u, v) in enumerate(sorted(G.edges())):
        G[u][v]["length"] = 100.0 + (i % 97) * 0.13
    return G


def _with_alt(G):
    """G에 Planar ALT 휴리스틱을 붙이고 info를 돌려준다."""
    heuristic, info = prepare_alt_heuristic(
        G, enabled=True, method="planar", k=4, seed=0
    )
    assert heuristic is not None, "toy grid에서 ALT 준비가 실패하면 안 된다."
    attach_alt_heuristic(G, heuristic, info)
    return info


# ────────────────────────────────────────────────
# 1. 주입해도 응답이 같은가
# ────────────────────────────────────────────────


@pytest.mark.parametrize("pair", [(99, 0), (0, 99), (55, 4), (90, 9)])
def test_alt_and_haversine_return_the_same_status_and_distance(pair):
    """동점이 있어도 status와 총 거리(최적 비용)는 항상 같아야 한다."""
    start, end = pair
    plain = _barrier_grid()
    alt = _barrier_grid()
    _with_alt(alt)

    plain_engine = OnewayAstarEngine(_route_input(plain, start, end), plain)
    alt_engine = OnewayAstarEngine(_route_input(alt, start, end), alt)

    plain_response = plain_engine.run()[0]
    alt_response = alt_engine.run()[0]

    assert plain_response.status == WalkRouteStatus.SUCCESS
    assert alt_response.status == plain_response.status
    assert alt_response.total_km == plain_response.total_km
    # 두 경로 모두 실제 최단거리와 비용이 같아야 한다(둘 다 최적해).
    optimal = nx.shortest_path_length(plain, start, end, weight="length")
    for engine, graph in ((plain_engine, plain), (alt_engine, alt)):
        cost = sum(
            graph[u][v]["length"]
            for u, v in zip(engine.last_path_nodes, engine.last_path_nodes[1:])
        )
        assert cost == pytest.approx(optimal)


@pytest.mark.parametrize("pair", [(99, 0), (0, 99), (55, 4), (90, 9)])
def test_alt_and_haversine_pick_the_same_path_when_no_ties_exist(pair):
    """최단경로가 유일하면 응답(status·coordinates·total_km)과 노드열까지 완전히 같다."""
    start, end = pair
    plain = _tie_free_grid()
    alt = _tie_free_grid()
    _with_alt(alt)

    plain_engine = OnewayAstarEngine(_route_input(plain, start, end), plain)
    alt_engine = OnewayAstarEngine(_route_input(alt, start, end), alt)

    plain_response = plain_engine.run()[0]
    alt_response = alt_engine.run()[0]

    assert plain_response.status == WalkRouteStatus.SUCCESS
    assert alt_response.status == plain_response.status
    assert _coords(alt_response) == _coords(plain_response)
    assert alt_response.total_km == plain_response.total_km
    assert alt_engine.last_path_nodes == plain_engine.last_path_nodes
    assert (
        alt_engine.last_path_nodes_by_candidate
        == plain_engine.last_path_nodes_by_candidate
    )


def test_alt_and_haversine_agree_when_visited_nodes_penalty_is_applied():
    """visited_nodes 페널티는 비용을 늘리기만 해서 ALT 하한을 깨지 않는다.

    동점의 영향을 빼고 페널티 자체만 보기 위해 동점 없는 grid를 쓴다.
    """
    start, end = 99, 0
    visited = {45, 46, 47, 55, 56, 57}

    plain = _tie_free_grid()
    alt = _tie_free_grid()
    _with_alt(alt)

    plain_engine = OnewayAstarEngine(
        _route_input(plain, start, end), plain, visited_nodes=set(visited)
    )
    alt_engine = OnewayAstarEngine(
        _route_input(alt, start, end), alt, visited_nodes=set(visited)
    )

    plain_response = plain_engine.run()[0]
    alt_response = alt_engine.run()[0]

    assert alt_response.status == plain_response.status
    assert _coords(alt_response) == _coords(plain_response)
    assert alt_response.total_km == plain_response.total_km
    assert alt_engine.last_path_nodes == plain_engine.last_path_nodes


def test_tie_breaking_may_differ_but_cost_never_does():
    """동점이 있는 grid에서 경로가 갈릴 수 있다는 사실 자체를 고정해 둔다.

    값(어느 쪽 경로가 나오는지)을 고정하지는 않는다 — networkx 구현이 바뀌면 달라질 수
    있다. 고정하는 것은 "비용은 항상 같다"뿐이다.
    """
    plain = _barrier_grid()
    alt = _barrier_grid()
    _with_alt(alt)

    plain_engine = OnewayAstarEngine(_route_input(plain, 99, 0), plain)
    alt_engine = OnewayAstarEngine(_route_input(alt, 99, 0), alt)
    plain_engine.run()
    alt_engine.run()

    optimal = nx.shortest_path_length(plain, 99, 0, weight="length")
    for engine, graph in ((plain_engine, plain), (alt_engine, alt)):
        cost = sum(
            graph[u][v]["length"]
            for u, v in zip(engine.last_path_nodes, engine.last_path_nodes[1:])
        )
        assert cost == pytest.approx(optimal)


# ────────────────────────────────────────────────
# 2. 휴리스틱 선택 순서
# ────────────────────────────────────────────────


def test_explicit_heuristic_argument_wins_over_the_attached_one():
    G = _barrier_grid()
    _with_alt(G)
    calls = []

    def explicit(u, v):
        calls.append((u, v))
        return 0.0

    engine = OnewayAstarEngine(_route_input(G, 99, 0), G, heuristic=explicit)
    response = engine.run()[0]

    assert engine.heuristic_name == "alt_injected"
    assert calls, "명시로 넘긴 휴리스틱이 실제로 호출되어야 한다."
    # h=0은 Dijkstra와 같아 여전히 admissible하므로 결과 경로는 같다.
    assert response.status == WalkRouteStatus.SUCCESS


def test_attached_alt_is_used_and_named_in_the_start_log(caplog):
    G = _barrier_grid()
    _with_alt(G)
    engine = OnewayAstarEngine(_route_input(G, 99, 0), G)

    with caplog.at_level(logging.INFO, logger="src.route_engine.engines.oneway_astar"):
        engine.run()

    assert engine.heuristic_name == "alt_planar"
    assert any("heuristic=alt_planar" in r.message for r in caplog.records)


def test_bare_graph_falls_back_to_haversine_and_says_so_in_the_log(caplog):
    G = _barrier_grid()  # 아무것도 붙이지 않았다
    engine = OnewayAstarEngine(_route_input(G, 99, 0), G)

    with caplog.at_level(logging.INFO, logger="src.route_engine.engines.oneway_astar"):
        response = engine.run()[0]

    assert engine.heuristic_name == "haversine"
    assert any("heuristic=haversine" in r.message for r in caplog.records)
    assert response.status == WalkRouteStatus.SUCCESS


def test_heuristic_method_is_preserved_when_alt_is_detached():
    G = _barrier_grid()
    _with_alt(G)
    attach_alt_heuristic(G, None, None)

    engine = OnewayAstarEngine(_route_input(G, 99, 0), G)

    assert engine.heuristic_name == "haversine"
    # _heuristic 메서드는 그대로 남아 있어야 한다(삭제하지 않았다).
    assert callable(engine._heuristic)
    assert engine._heuristic(99, 0) >= 0.0
