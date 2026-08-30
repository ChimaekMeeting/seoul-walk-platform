"""ALT(A* + Landmark + Triangle inequality) 선택법들이 공유하는 인프라.

랜드마크-전체노드 거리표, 삼각부등식 휴리스틱, admissibility 검증을 담당한다.
개별 선택법(Random/Farthest/Planar)은 각자 파일에서 이 모듈만 가져다 쓴다.
어떤 엔진에도 연결하지 않은 독립 모듈이다 — 현재 프로덕션 OnewayAstarEngine은
weight=length(거리 전용)로 바뀌면서 Haversine 휴리스틱만으로도 admissible해
랜드마크 ALT를 쓰지 않는다(2026-08-23, route_engine/README.md
"oneway_shortest 엔진" 절 참고).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import inf

import networkx as nx

from src.route_engine.engines.path_utils import PathUtils

LandmarkTable = dict[int, dict[int, float]]  # landmark_id -> {node_id: dist(m)}


def _largest_component_nodes(G: nx.Graph) -> list[int]:
    """PathUtils.find_nearest_node과 동일하게 최대 연결요소로 후보를 제한한다.
    탐색 시작점이 이 요소 밖에 있을 수 없으므로, 랜드마크도 여기서만 고르면
    모든 탐색 쌍에 대해 도달 가능한 랜드마크를 보장할 수 있다.
    """
    if G.is_directed():
        largest_cc = max(nx.weakly_connected_components(G), key=len)
    else:
        largest_cc = max(nx.connected_components(G), key=len)
    return list(largest_cc)


def precompute_landmark_distances(
    G: nx.Graph, landmarks: Sequence[int], *, weight: str = "length"
) -> LandmarkTable:
    """랜드마크별 전체 노드까지의 실제 도로망 거리(m)를 미리 계산한다.
    무방향 그래프 기준이라 dist(L, u) == dist(u, L)이며 정방향 표만으로 충분하다.
    도달 불가한 노드는 결과 dict에 아예 포함되지 않는다(무한대를 명시 저장하지 않음).
    """
    return {
        lm: dict(nx.single_source_dijkstra_path_length(G, lm, weight=weight))
        for lm in landmarks
    }


def build_alt_heuristic(G: nx.Graph, landmarks: Sequence[int], *, weight: str = "length"):
    """nx.astar_path(heuristic=...)에 바로 넘길 수 있는 휴리스틱 함수와, 함께 계산한
    LandmarkTable을 반환한다."""
    table = precompute_landmark_distances(G, landmarks, weight=weight)

    def heuristic(u: int, v: int) -> float:
        return alt_heuristic(table, u, v)

    return heuristic, table


def alt_heuristic(landmark_dist: LandmarkTable, u: int, v: int) -> float:
    """삼각부등식 기반 h(u,v) = max_L |dist(L,u) - dist(L,v)|.
    랜드마크가 u 또는 v에 도달하지 못하면(표에 값 없음) 해당 랜드마크는 건너뛴다.
    모든 랜드마크가 건너뛰어지면 0.0을 반환한다(정보 없음이지만 여전히 admissible).
    """
    best = 0.0
    for dist in landmark_dist.values():
        du = dist.get(u)
        dv = dist.get(v)
        if du is None or dv is None:
            continue
        diff = du - dv if du >= dv else dv - du
        if diff > best:
            best = diff
    return best


@dataclass(frozen=True)
class AdmissibilityReport:
    checked_pairs: int
    alt_violations: int
    max_alt_violation_m: float
    haversine_violations: int
    max_haversine_violation_m: float
    mean_alt_h_m: float
    mean_haversine_h_m: float
    mean_actual_m: float


def verify_admissible(
    G: nx.Graph,
    landmark_dist: LandmarkTable,
    *,
    weight: str = "length",
    pairs: Sequence[tuple[int, int]],
) -> AdmissibilityReport:
    """샘플 (u, v) 쌍마다 h_ALT(u,v) <= 실제 최단거리를 만족하는지, 같은 조건에서
    Haversine 휴리스틱도 admissible한지 함께 검사한다. pairs는 호출자가 정한다
    (이 함수는 표본을 만들지 않는다). 부동소수 오차를 감안해 1e-6m 초과분만
    위반으로 센다.
    """
    checked = 0
    alt_violations = 0
    max_alt_violation = 0.0
    haversine_violations = 0
    max_haversine_violation = 0.0
    sum_alt = 0.0
    sum_hav = 0.0
    sum_actual = 0.0

    for u, v in pairs:
        try:
            actual = nx.shortest_path_length(G, u, v, weight=weight)
        except nx.NetworkXNoPath:
            continue

        h_alt = alt_heuristic(landmark_dist, u, v)
        nu, nv = G.nodes[u], G.nodes[v]
        h_hav = PathUtils._haversine_m(
            nu.get("lat", 0), nu.get("lon", 0), nv.get("lat", 0), nv.get("lon", 0)
        )

        checked += 1
        sum_alt += h_alt
        sum_hav += h_hav
        sum_actual += actual

        over_alt = h_alt - actual
        if over_alt > 1e-6:
            alt_violations += 1
            max_alt_violation = max(max_alt_violation, over_alt)

        over_hav = h_hav - actual
        if over_hav > 1e-6:
            haversine_violations += 1
            max_haversine_violation = max(max_haversine_violation, over_hav)

    if checked == 0:
        raise ValueError("도달 가능한 (u, v) 쌍이 없습니다.")

    return AdmissibilityReport(
        checked_pairs=checked,
        alt_violations=alt_violations,
        max_alt_violation_m=max_alt_violation,
        haversine_violations=haversine_violations,
        max_haversine_violation_m=max_haversine_violation,
        mean_alt_h_m=sum_alt / checked,
        mean_haversine_h_m=sum_hav / checked,
        mean_actual_m=sum_actual / checked,
    )
