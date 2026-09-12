"""시각화 회귀 테스트가 함께 쓰는 toy 도보망.

실제 artifact(16만 노드)를 쓰지 않는다. 5×5 격자 두 벌로 "동점이 많은 입력"과
"동점이 없는 입력"을 모두 돌려 본다 — A* 재생이 동점 처리까지 실제 탐색과 같은지
확인하려면 두 경우가 다 필요하다.
"""

import math

import networkx as nx
import pytest


def _grid_graph():
    graph = nx.convert_node_labels_to_integers(nx.grid_2d_graph(5, 5))
    for n in graph:
        graph.nodes[n].update(lat=37 + (n // 5) * .001, lon=127 + (n % 5) * .001)
    return graph


@pytest.fixture
def grid():
    """모든 간선이 120m인 5×5 격자. 같은 f 값이 여럿 나오는(동점 있는) 입력이다."""
    graph = _grid_graph()
    nx.set_edge_attributes(graph, 120.0, "length")
    return graph


@pytest.fixture
def varied_grid():
    """간선 길이를 서로 다르게 준 5×5 격자(동점 없음).

    길이는 모두 131m 이상이라 좌표 간격(위도 0.001도 ≈ 111m)보다 길다 — Haversine
    직선거리가 실제 도로 거리를 넘지 않아 admissible 전제가 유지된다. 서로 다른
    무리수를 더하므로 경로 비용이 우연히 같아지지 않는다.
    """
    graph = _grid_graph()
    for i, (u, v) in enumerate(sorted(graph.edges())):
        graph[u][v]["length"] = 130.0 + math.sqrt(i + 2)
    return graph
