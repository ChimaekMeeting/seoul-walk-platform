"""Random 랜드마크 선택법의 재현성·범위 검증과 ALT 휴리스틱 admissibility 검증."""

import networkx as nx
import pytest

from src.route_engine.landmark_random import select_landmarks_random
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


def test_select_landmarks_random_returns_k_distinct_nodes_and_is_reproducible():
    G = _grid_graph()
    a = select_landmarks_random(G, 5, seed=1)
    b = select_landmarks_random(G, 5, seed=1)
    assert a == b
    assert len(set(a)) == 5
    assert set(a) <= set(G.nodes)


def test_select_landmarks_random_differs_between_seeds():
    G = _grid_graph()
    assert select_landmarks_random(G, 5, seed=0) != select_landmarks_random(G, 5, seed=1)


def test_select_landmarks_random_rejects_k_below_one():
    G = _grid_graph(rows=2, cols=2)
    with pytest.raises(ValueError):
        select_landmarks_random(G, 0, seed=0)


def test_select_landmarks_random_rejects_k_too_large():
    G = _grid_graph(rows=2, cols=2)
    with pytest.raises(ValueError):
        select_landmarks_random(G, 10, seed=0)


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_select_landmarks_random_gives_admissible_alt_heuristic(seed):
    G = _grid_graph()
    landmarks = select_landmarks_random(G, 4, seed=seed)
    table = precompute_landmark_distances(G, landmarks, weight="length")
    nodes = list(G.nodes)
    pairs = [(nodes[i], nodes[j]) for i in range(len(nodes)) for j in range(i + 1, len(nodes))]

    report = verify_admissible(G, table, weight="length", pairs=pairs)

    assert report.alt_violations == 0
    assert report.haversine_violations == 0
    assert report.checked_pairs == len(pairs)
