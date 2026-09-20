""""서로 다른 경로 수" 집계 유틸.

benchmarks/results.py::RESULT_COLUMNS에는 노드열 자체가 없다(build_result_row가
paths를 지표로만 요약하고 버린다). "[TEST] 가중치 반영 후 GRASP+ALNS 검증"(#495) 이슈의
To-Do("서로 다른 경로 수")를 재려면 solver.solve()가 반환하는 raw_result["paths"]를 직접
받아야 하므로, 이 지표가 필요한 러너는 run_benchmark()의 멀티프로세스 격리 대신
solver.solve()를 직접 호출해 raw paths를 확보해야 한다(run_grasp_alns_weighted_check.py
참고).

경로 동일성 기준: 순환 경로는 시작점 회전(rotation)이나 진행 방향이 달라도 사람이
보기엔 "같은 경로"이므로, 무방향 간선 집합(edge set)이 같으면 같은 경로로 센다.
간선 집합이 아니라 노드열 자체를 기준으로 하면 회전·방향만 다른 동일 경로를 서로
다른 경로로 잘못 셀 수 있다.
"""
from __future__ import annotations

import hashlib
from itertools import combinations
from typing import Optional


def canonical_route_key(path: list) -> frozenset:
    """노드열 하나를 회전·방향 무관 간선 집합으로 정규화한다.

    path는 닫힌 순환 경로(path[0] == path[-1])를 가정한다. 무방향 간선을
    frozenset({u, v})로 만들어 방향을 지우고, 그 간선들의 frozenset으로 시작점
    회전도 지운다.
    """
    edges = frozenset(
        frozenset((u, v)) for u, v in zip(path, path[1:])
    )
    return edges


def route_signature(path: list) -> Optional[str]:
    """방향·시작 표현과 무관한 간선 집합의 안정적인 SHA-256 식별자.

    원자료 노드열을 CSV에 넣지 않고도, 동일 조건의 거리 전용·가중 경로가 실제로
    달라졌는지 짝지어 비교할 수 있게 한다. 노드 ID의 타입이 섞여도 repr 문자열로
    정렬하므로 Python hash seed나 Graph 삽입 순서에 흔들리지 않는다.
    """
    if not path or len(path) < 2:
        return None
    edges = []
    for left, right in zip(path, path[1:]):
        a, b = sorted((repr(left), repr(right)))
        edges.append(f"{a}|{b}")
    payload = "\n".join(sorted(set(edges))).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def count_distinct_routes(paths: list[list]) -> int:
    """path 목록(각 path는 노드 id 리스트) 중 서로 다른 경로의 개수."""
    return len({canonical_route_key(p) for p in paths})


def distinct_route_report(paths: list[list]) -> dict:
    """개수뿐 아니라 각 고유 경로가 몇 번 나왔는지(빈도)까지 반환.

    "5개 미만이면 되돌아간다" 기준 판단에, 단순 개수 말고 "한 경로가 압도적으로
    자주 나오는가"도 같이 보고 싶을 때 쓴다.
    """
    keys = [canonical_route_key(p) for p in paths]
    counts: dict[frozenset, int] = {}
    for k in keys:
        counts[k] = counts.get(k, 0) + 1
    return {
        "n_routes_total": len(paths),
        "n_distinct_routes": len(counts),
        "frequency_of_most_common": max(counts.values()) if counts else 0,
        "distinct_route_sizes": sorted(counts.values(), reverse=True),
    }


def candidate_pairwise_overlap_ratio(graph, paths: list[list], expected_count: int = 3) -> Optional[float]:
    """반환 후보 간 구간 중첩의 거리 가중 Jaccard 평균을 계산한다.

    각 후보 쌍에서 ``공통 간선 길이 / 합집합 간선 길이``를 구한 뒤 평균낸다. 따라서
    완전히 같은 세 후보는 1.0, 공통 구간이 전혀 없으면 0.0이다. 개별 후보 안에서의
    자기 재통행은 ``repeated_edge_ratio``가 별도로 측정하므로 여기서는
    ``canonical_route_key()``의 간선 집합만 쓴다.

    이 지표는 최종 경로 + 대안 2개라는 3후보 계약을 가진 순환 엔진에만 의미가 있다.
    편도처럼 후보가 하나이거나 후보 생성이 실패한 경우에는 0.0으로 위장하지 않고 None을
    반환한다.
    """
    if graph is None or len(paths) != expected_count:
        return None

    try:
        edge_sets = [canonical_route_key(path) for path in paths]
        pairwise = []
        for left, right in combinations(edge_sets, 2):
            union = left | right
            if not union:
                return None

            def edge_length(edge) -> float:
                u, v = tuple(edge)
                return float(graph[u][v]["length"])

            shared_m = sum(edge_length(edge) for edge in left & right)
            union_m = sum(edge_length(edge) for edge in union)
            if union_m <= 0:
                return None
            pairwise.append(shared_m / union_m)
        return round(sum(pairwise) / len(pairwise), 4) if pairwise else None
    except (KeyError, TypeError, ValueError):
        return None
