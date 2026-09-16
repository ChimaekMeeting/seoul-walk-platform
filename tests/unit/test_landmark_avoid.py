"""Avoid 랜드마크 선택법의 size(v) 계산·하강 로직과 admissibility 검증."""

import networkx as nx
import pytest

from src.route_engine.landmark_avoid import (
    _select_avoid_landmark,
    select_landmarks_avoid,
)
from src.route_engine.landmark_shared import (
    precompute_landmark_distances,
    verify_admissible,
)

_BASE_LAT, _BASE_LON = 37.50, 127.00

# 손으로 계산 가능한 고정 트리: 0 -> {1, 2}, 1 -> {3, 4}, 2 -> {5}
#   weight(0..5) = [0, 1, 1, 2, 2, 2] (모두 S=∅일 때의 dist(r, v))
_CHILDREN = {0: [1, 2], 1: [3, 4], 2: [5], 3: [], 4: [], 5: []}
_WEIGHT = {0: 0.0, 1: 1.0, 2: 1.0, 3: 2.0, 4: 2.0, 5: 2.0}


def test_select_avoid_landmark_with_no_existing_landmarks_descends_heaviest_branch():
    # size(1)=1+2+2=5, size(2)=1+2=3 -> 루트에서 1(a)로. size(3)=size(4)=2 동점 ->
    # 노드 ID가 작은 3이 이긴다.
    leaf = _select_avoid_landmark(_CHILDREN, root=0, weight_by_node=_WEIGHT, landmark_set=set())
    assert leaf == 3


def test_select_avoid_landmark_skips_subtree_containing_existing_landmark():
    # 4가 이미 랜드마크 -> size(1)이 0으로 오염되어 루트도 0. 남은 후보 중
    # size(2)=1+2=3이 최댓값 -> w=2, 유일한 자식 5가 리프.
    leaf = _select_avoid_landmark(
        _CHILDREN, root=0, weight_by_node=_WEIGHT, landmark_set={4}
    )
    assert leaf == 5


def test_select_avoid_landmark_never_repicks_the_contaminated_branch():
    # 두 자식(3, 4) 서브트리 전체가 이미 오염되면(둘 다 랜드마크) 루트 자체가
    # 유일하게 남은, 이미 랜드마크가 없는 노드다.
    leaf = _select_avoid_landmark(
        {0: []}, root=0, weight_by_node={0: 0.0}, landmark_set=set()
    )
    assert leaf == 0


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


def test_select_landmarks_avoid_returns_k_distinct_nodes_and_is_reproducible():
    G = _grid_graph()
    a = select_landmarks_avoid(G, 5, seed=1)
    b = select_landmarks_avoid(G, 5, seed=1)
    assert a == b
    assert len(set(a)) == 5
    assert set(a) <= set(G.nodes)


def test_select_landmarks_avoid_rejects_k_too_large():
    G = _grid_graph(rows=2, cols=2)
    with pytest.raises(ValueError):
        select_landmarks_avoid(G, 10, seed=0)


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_select_landmarks_avoid_gives_admissible_alt_heuristic(seed):
    G = _grid_graph()
    landmarks = select_landmarks_avoid(G, 4, seed=seed)
    table = precompute_landmark_distances(G, landmarks, weight="length")
    nodes = list(G.nodes)
    pairs = [(nodes[i], nodes[j]) for i in range(len(nodes)) for j in range(i + 1, len(nodes))]

    report = verify_admissible(G, table, weight="length", pairs=pairs)

    assert report.alt_violations == 0
    assert report.haversine_violations == 0
    assert report.checked_pairs == len(pairs)
