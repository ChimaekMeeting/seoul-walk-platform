"""Avoid 랜드마크 선택법(Goldberg & Werneck, "Computing Point-to-Point Shortest
Paths from External Memory", 2005, §6.3.4 "Avoid").

좌표가 아니라 그래프 구조(최단경로 트리)만으로 기존 랜드마크 집합이 잘 덮지
못하는 영역을 찾아, 그 영역에서 가장 안 덮인 리프 노드를 다음 랜드마크로
고르는 과정을 k번 반복한다. 공용 인프라(LandmarkTable, alt_heuristic,
precompute_landmark_distances, _largest_component_nodes)는 landmark_shared.py를
그대로 쓴다.

참고: 작업 티켓은 Goldberg, Kaplan, Werneck의 "Reach for A*"(2006, MSR-TR-2005-132)
를 참고 논문으로 표기했다. 2026-08-30 원문 확인 결과 그 논문의 앞부분(개요·관련
연구)에는 Avoid 선택법 자체가 나오지 않았다(전체를 다 읽지는 못함). Avoid의
size(v)/서브트리 하강 절차가 pseudocode 수준으로 명확히 나온 곳은 같은 저자
그룹의 Goldberg & Werneck(2005) §6.3.4였고, 이 구현은 그 절을 기준으로 삼았다.
"""

from __future__ import annotations

import random

import networkx as nx

from src.route_engine.landmark_shared import (
    LandmarkTable,
    _largest_component_nodes,
    alt_heuristic,
    precompute_landmark_distances,
)


def _subtree_children(pred: dict[int, list[int]]) -> dict[int, list[int]]:
    """nx.dijkstra_predecessor_and_distance의 pred 결과에서 SPT의 자식 맵을 만든다.
    동점 predecessor가 여러 개면 첫 번째만 부모로 써서 단일 트리로 단순화한다."""
    children: dict[int, list[int]] = {v: [] for v in pred}
    for v, plist in pred.items():
        if plist:
            children[plist[0]].append(v)
    return children


def _select_avoid_landmark(
    children: dict[int, list[int]],
    root: int,
    weight_by_node: dict[int, float],
    landmark_set: set[int],
) -> int:
    """SPT(children)와 노드별 weight(v), 기존 랜드마크 집합으로 다음 Avoid
    랜드마크(리프 노드)를 고른다. Goldberg & Werneck(2005) §6.3.4의 size(v) 계산과
    최대 size 자식으로의 하강을 그대로 따른다. 동점은 노드 ID가 작은 쪽을 우선한다.
    """
    order: list[int] = [root]
    stack = [root]
    while stack:
        u = stack.pop()
        for c in children.get(u, []):
            order.append(c)
            stack.append(c)

    size: dict[int, float] = {}
    contains_landmark: dict[int, bool] = {}
    for v in reversed(order):
        has_landmark = v in landmark_set or any(
            contains_landmark[c] for c in children.get(v, [])
        )
        contains_landmark[v] = has_landmark
        if has_landmark:
            size[v] = 0.0
        else:
            size[v] = weight_by_node[v] + sum(size[c] for c in children.get(v, []))

    w = max(order, key=lambda v: (size[v], -v))
    leaf = w
    while children.get(leaf):
        leaf = max(children[leaf], key=lambda c: (size[c], -c))
    return leaf


def select_landmarks_avoid(
    G: nx.Graph, k: int, *, weight: str = "length", seed: int = 0
) -> list[int]:
    """Avoid 랜드마크 선택법. k회 반복하며 매번:

    1. 루트 r을 무작위로 고르고 최단경로 트리(SPT) T_r을 만든다.
    2. 모든 노드 v의 weight(v) = dist(r,v) - 현재 랜드마크 집합 S 기준 ALT 하한을
       구한다(S가 비어있으면 하한이 항상 0이라 weight(v) = dist(r,v) — 이 경우 논문의
       size(v)는 서브트리 전체 거리 합으로 줄어들어, 첫 랜드마크는 루트에서 가장
       무거운 가지를 따라 리프까지 내려가는 것과 같아진다).
    3. size(v)를 후위 순회로 구한다 — v의 서브트리(자신 포함)에 기존 랜드마크가
       하나라도 있으면 0, 없으면 서브트리 전체 weight 합.
    4. size가 가장 큰 노드 w를 고르고(기존 랜드마크가 없는, 가장 안 덮인 영역),
       w에서 시작해 항상 size가 가장 큰 자식으로 내려가 리프에 도달하면 그 리프를
       새 랜드마크로 추가한다.

    Farthest처럼 반복마다 SSSP가 필요하고(루트 SPT 1회 + 새 랜드마크 자체 거리표
    1회 = 반복당 2회), 매 반복 전체 노드에 대해 ALT 하한도 다시 계산해(반복당
    O(n·|S|)) Farthest보다 전처리 비용이 크다 — 부팅 경로가 아니라 실험·벤치마크
    용도다.

    최대 연결요소가 이미 기존 랜드마크로 전부 '덮여서'(모든 노드의 size가 0) 더
    이상 안 덮인 리프를 찾을 수 없는 극단적인 경우, 아직 안 뽑힌 노드 중 하나를
    무작위로 대신 골라 항상 서로 다른 k개를 반환한다(원 논문에는 없는 이 구현의
    방어적 처리).
    """
    if k < 1:
        raise ValueError("k는 1 이상이어야 합니다.")
    nodes = _largest_component_nodes(G)
    if k > len(nodes):
        raise ValueError("k가 최대 연결요소의 노드 수보다 큽니다.")

    rng = random.Random(seed)
    landmarks: list[int] = []
    landmark_set: set[int] = set()
    table: LandmarkTable = {}

    for _ in range(k):
        r = rng.choice(nodes)
        pred, dist = nx.dijkstra_predecessor_and_distance(G, r, weight=weight)
        children = _subtree_children(pred)

        if table:
            weight_by_node = {v: d - alt_heuristic(table, r, v) for v, d in dist.items()}
        else:
            weight_by_node = dist

        leaf = _select_avoid_landmark(children, r, weight_by_node, landmark_set)
        if leaf in landmark_set:
            remaining = [n for n in nodes if n not in landmark_set]
            leaf = rng.choice(remaining)

        landmarks.append(leaf)
        landmark_set.add(leaf)
        table[leaf] = precompute_landmark_distances(G, [leaf], weight=weight)[leaf]

    return landmarks
