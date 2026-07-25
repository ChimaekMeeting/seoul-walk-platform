"""
benchmarks/solvers/_oneway_engine_common.py

oneway_beam / oneway_grasp / oneway_alns / oneway_rcsp / oneway_plateau 다섯 엔진
모두 동일한 구조를 가진다:
  1) calculate_custom_score(G, ...)로 edge별 가중치 점수 부여
  2) find_path(start, end, target_km)로 노드ID 경로 생성 (circular과 달리 3인자)
  3) prune_dead_ends(nodes)로 왕복 잔가지 제거

circular 버전(_circular_engine_common.py)과 동일한 이유로 engine.run() 대신
좌표 변환 이전 단계(노드ID 경로)를 재현해서 사용한다 (엔진 알고리즘 자체는 안 건드림).
"""

import networkx as nx

from src.route_engine.scoring.scoring_engine import calculate_custom_score


def run_oneway_engine(engine, start_node: int, end_node: int, target_km: float) -> tuple[list, float]:
    """OnewayXxxEngine 인스턴스에서 노드ID 경로와 누적 custom_score(cost)를 얻는다.

    경로 생성에 실패하면(빈 경로/잔가지 제거 후 경로 소실) ValueError를 던진다 —
    벤치마크 하네스가 이를 status="failed" 행으로 안전하게 처리한다.
    """
    calculate_custom_score(engine.G, {
        "mode": engine.scoring_mode,
        "weights": engine.weights,
        "blocked_tags": engine.blocked_tags,
    })

    nodes = engine.find_path(start_node, end_node, target_km)
    if not nodes or len(nodes) < 2:
        raise ValueError("경로 생성 실패: 유효한 편도 경로를 찾지 못했습니다 (NO_PATH)")

    pruned = engine.utils.prune_dead_ends(nodes)
    if len(pruned) < 2:
        raise ValueError("경로 생성 실패: 잔가지 제거 후 남은 경로가 없습니다")

    _, cost = engine.utils.metrics(pruned)
    return pruned, cost


def base_shortest_path_overlap_ratio(engine, pruned_path: list, start_node: int, end_node: int) -> float:
    """pruned_path가 베이스 최단경로(custom_score 기준)와 겹치는 구간의 거리 비율을 반환한다.

    engine.G는 run_oneway_engine 호출 이후 이미 custom_score가 계산돼 있어야 한다.
    Plateau처럼 '베이스 경로와 얼마나 안 겹치는가'가 알고리즘 핵심 지표인 solver에서 사용
    (benchmark.py의 edge_overlap_ratio는 '자기 자신과의 왕복 중복'이라 다른 지표임).
    """
    try:
        base_path = nx.shortest_path(engine.G, start_node, end_node, weight="custom_score")
    except nx.NetworkXNoPath:
        return 0.0

    base_edges = {frozenset((base_path[i], base_path[i + 1])) for i in range(len(base_path) - 1)}

    total_m = sum(
        (engine.G.get_edge_data(pruned_path[i], pruned_path[i + 1]) or {}).get("length", 0)
        for i in range(len(pruned_path) - 1)
    )
    if total_m <= 0:
        return 0.0

    overlap_m = sum(
        (engine.G.get_edge_data(pruned_path[i], pruned_path[i + 1]) or {}).get("length", 0)
        for i in range(len(pruned_path) - 1)
        if frozenset((pruned_path[i], pruned_path[i + 1])) in base_edges
    )
    return round(overlap_m / total_m, 4)
