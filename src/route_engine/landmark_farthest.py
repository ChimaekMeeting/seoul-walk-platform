"""Farthest 랜드마크 선택법(Goldberg & Harrelson, "Computing the Shortest Path:
A* Search Meets Graph Theory", SODA 2005).

이미 뽑힌 랜드마크 집합에서 도로망 거리로 가장 멀리 떨어진 노드를 다음 랜드마크로
고르는 과정을 k번 반복해, 그래프 외곽에 고르게 퍼진 랜드마크 집합을 만든다.
공용 인프라(_largest_component_nodes, precompute_landmark_distances,
alt_heuristic, verify_admissible)는 landmark_shared.py를 그대로 쓰고 이 파일은
선택만 한다 — 공용 모듈에 새로 추가한 함수는 없다. Random/Planar/Avoid와
마찬가지로 어떤 엔진에도 연결하지 않은 독립 모듈이다.
"""

from __future__ import annotations

import random

import networkx as nx

from src.route_engine.landmark_shared import (
    _largest_component_nodes,
    precompute_landmark_distances,
)


def select_landmarks_farthest(
    G: nx.Graph, k: int, *, weight: str = "length", seed: int = 0
) -> list[int]:
    """Farthest 랜드마크 선택법.

    1. `_largest_component_nodes(G)`로 후보를 최대 연결요소로 제한하고, 첫
       랜드마크를 `random.Random(seed).choice`로 무작위로 고른다.
    2. 새 랜드마크를 추가할 때마다 그 랜드마크 1개의 SSSP를
       `precompute_landmark_distances`로 1회 돌려, 노드별 "현재 랜드마크 집합까지의
       최소 거리" `min_dist(v) = min_{L in S} dist(L, v)`를 갱신한다.
    3. 아직 뽑히지 않은 후보 중 `min_dist(v)`가 가장 큰 노드를 다음 랜드마크로
       고른다. 동점이면 노드 ID가 작은 쪽을 우선한다(원 논문에 없는 이 구현의 결정).
    4. k개가 찰 때까지 2~3을 반복한다 — 전체 SSSP 횟수는 정확히 k회다.

    `min_dist`는 해당 노드에 실제로 도달한 랜드마크만으로 계산하며, 어떤
    랜드마크에서도 도달하지 못한 노드는 후보에서 아예 제외한다(그런 노드는 ALT
    하한을 전혀 못 받으므로 "가장 먼 노드"로 뽑아도 의미가 없다). 무방향 그래프는
    최대 연결요소 안에서 모두 서로 도달 가능하므로 이 제외가 발생하지 않는다.

    Raises:
        ValueError: k가 1 미만이거나, 최대 연결요소의 노드 수보다 클 때.
        ValueError: (방어적 처리) 도달 가능한 후보가 다 떨어져 k개를 채울 수 없을 때.
            무방향 그래프에서는 발생하지 않는다.
    """
    if k < 1:
        raise ValueError("k는 1 이상이어야 합니다.")
    nodes = _largest_component_nodes(G)
    if k > len(nodes):
        raise ValueError("k가 최대 연결요소의 노드 수보다 큽니다.")

    rng = random.Random(seed)
    first = rng.choice(nodes)
    landmarks = [first]
    chosen = {first}
    min_dist: dict[int, float] = dict(
        precompute_landmark_distances(G, [first], weight=weight)[first]
    )

    while len(landmarks) < k:
        candidates = [v for v in min_dist if v not in chosen]
        if not candidates:
            raise ValueError("도달 가능한 후보가 없어 k개를 채울 수 없습니다.")

        nxt = max(candidates, key=lambda v: (min_dist[v], -v))
        landmarks.append(nxt)
        chosen.add(nxt)

        row = precompute_landmark_distances(G, [nxt], weight=weight)[nxt]
        for v, d in row.items():
            current = min_dist.get(v)
            if current is None or d < current:
                min_dist[v] = d

    return landmarks
