"""Random 랜드마크 선택법(Goldberg & Harrelson, "Computing the Shortest Path:
A* Search Meets Graph Theory", SODA 2005에서 다른 선택법의 기준선으로 쓴 방식).

최대 연결요소에서 k개 노드를 균등 무작위로 뽑는 가장 단순한 선택법이며, 다른
선택법(Farthest/Planar/Avoid)의 h(n) 품질을 비교할 때 기준선(baseline) 역할을
한다. 공용 인프라(LandmarkTable, precompute_landmark_distances, alt_heuristic,
verify_admissible)는 landmark_shared.py를 그대로 쓰고 이 파일은 선택만 한다 —
공용 모듈에 새로 추가한 함수는 없다. 2026-09-12부터 alt_runtime.py가 이 선택법을
WALK_ALT_METHOD=random 설정으로 쓸 수 있게 열어 뒀다(기본값은 planar) — seed에 따라
결과가 달라져 기본 선택법으로는 쓰지 않는다.
"""

from __future__ import annotations

import random

import networkx as nx

from src.route_engine.landmark_shared import _largest_component_nodes


def select_landmarks_random(G: nx.Graph, k: int, *, seed: int = 0) -> list[int]:
    """Random 랜드마크 선택법.

    `_largest_component_nodes(G)`로 후보를 최대 연결요소로 제한한 뒤
    `random.Random(seed).sample`로 서로 다른 k개를 뽑는다. 도로망 거리 계산(SSSP)도
    좌표 계산도 전혀 하지 않아 네 선택법 중 선택 자체가 가장 저렴하다 — 거리표는
    호출자가 `precompute_landmark_distances`로 따로 만든다.

    같은 그래프·같은 seed면 항상 같은 결과를 반환한다.

    Raises:
        ValueError: k가 1 미만이거나, 최대 연결요소의 노드 수보다 클 때.
    """
    if k < 1:
        raise ValueError("k는 1 이상이어야 합니다.")
    nodes = _largest_component_nodes(G)
    if k > len(nodes):
        raise ValueError("k가 최대 연결요소의 노드 수보다 큽니다.")

    return random.Random(seed).sample(nodes, k)
