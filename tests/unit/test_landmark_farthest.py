"""Farthest 랜드마크 선택법의 선택 순서·재현성 검증과 ALT 휴리스틱 admissibility 검증."""

import networkx as nx
import pytest

from src.route_engine.landmark_farthest import select_landmarks_farthest
from src.route_engine.landmark_shared import (
    precompute_landmark_distances,
    verify_admissible,
)

_BASE_LAT, _BASE_LON = 37.50, 127.00


def _grid_graph(rows=6, cols=6, edge_length=100.0):
    """좌표 간격을 length보다 훨씬 작게 잡아(수 미터 이내) Haversine admissibility
    전제를 만족하는 toy 그래프 — route_engine/README.md의 admissibility 전제 절 참고."""
    G = nx.Graph()
    for r in range(rows):
        for c in range(cols):
            node = r * cols + c
            G.add_node(node, lat=_BASE_LAT + r * 0.00005, lon=_BASE_LON + c * 0.00005)
    for r in range(rows):
        for c in range(cols):
            node = r * cols + c
            if c + 1 < cols:
                G.add_edge(node, node + 1, length=edge_length)
            if r + 1 < rows:
                G.add_edge(node, node + cols, length=edge_length)
    return G


def _line_graph(n=5, edge_length=100.0):
    """0-1-2-3-4를 100m 간격으로 이은 일직선 그래프. dist(i, j) = |i - j| * 100m라
    선택 순서를 손으로 계산할 수 있다."""
    G = nx.Graph()
    for i in range(n):
        G.add_node(i, lat=_BASE_LAT, lon=_BASE_LON + i * 0.00005)
    for i in range(n - 1):
        G.add_edge(i, i + 1, length=edge_length)
    return G


def test_farthest_selection_order_on_a_line_starting_from_an_endpoint():
    # seed 2 -> 첫 랜드마크 0(무작위). 이후 손계산:
    #   min_dist = {0:0, 1:100, 2:200, 3:300, 4:400} -> 최댓값 4번 노드(400m)
    #   4 추가 후 min_dist = {0:0, 1:100, 2:200, 3:100, 4:0} -> 2번 노드(200m)
    #   2 추가 후 min_dist = {0:0, 1:100, 2:0, 3:100, 4:0} -> 1과 3이 100m 동점,
    #     동점은 노드 ID가 작은 쪽이라 1
    #   마지막 남은 후보는 3
    assert select_landmarks_farthest(_line_graph(), 5, seed=2) == [0, 4, 2, 1, 3]


def test_farthest_selection_order_on_a_line_starting_from_an_inner_node():
    # seed 0 -> 첫 랜드마크 3(무작위). 이후 손계산:
    #   min_dist = {0:300, 1:200, 2:100, 3:0, 4:100} -> 0번 노드(300m)
    #   0 추가 후 min_dist = {0:0, 1:100, 2:100, 3:0, 4:100} -> 1, 2, 4가 100m 동점
    #     -> 노드 ID가 가장 작은 1
    #   1 추가 후 min_dist = {2:100, 4:100} -> 다시 동점, 노드 ID가 작은 2
    assert select_landmarks_farthest(_line_graph(), 4, seed=0) == [3, 0, 1, 2]


def test_select_landmarks_farthest_returns_k_distinct_nodes_and_is_reproducible():
    G = _grid_graph()
    a = select_landmarks_farthest(G, 5, seed=1)
    b = select_landmarks_farthest(G, 5, seed=1)
    assert a == b
    assert len(set(a)) == 5
    assert set(a) <= set(G.nodes)


def test_select_landmarks_farthest_differs_between_seeds():
    G = _grid_graph()
    assert select_landmarks_farthest(G, 4, seed=0) != select_landmarks_farthest(G, 4, seed=1)


def test_select_landmarks_farthest_rejects_k_below_one():
    G = _grid_graph(rows=2, cols=2)
    with pytest.raises(ValueError):
        select_landmarks_farthest(G, 0, seed=0)


def test_select_landmarks_farthest_rejects_k_too_large():
    G = _grid_graph(rows=2, cols=2)
    with pytest.raises(ValueError):
        select_landmarks_farthest(G, 10, seed=0)


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_select_landmarks_farthest_gives_admissible_alt_heuristic(seed):
    G = _grid_graph()
    landmarks = select_landmarks_farthest(G, 4, seed=seed)
    table = precompute_landmark_distances(G, landmarks, weight="length")
    nodes = list(G.nodes)
    pairs = [(nodes[i], nodes[j]) for i in range(len(nodes)) for j in range(i + 1, len(nodes))]

    report = verify_admissible(G, table, weight="length", pairs=pairs)

    assert report.alt_violations == 0
    assert report.haversine_violations == 0
    assert report.checked_pairs == len(pairs)
