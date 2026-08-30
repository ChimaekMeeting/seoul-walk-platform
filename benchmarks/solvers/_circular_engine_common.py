"""
benchmarks/solvers/_circular_engine_common.py

circular_grasp / circular_beam / circular_alns 세 엔진 모두 동일한 구조를 가진다:
  1) calculate_custom_score(G, ...)로 edge별 가중치 점수 부여
  2) find_path(start_node, target_km)로 노드ID 경로 생성
  3) prune_dead_ends(nodes)로 왕복 잔가지 제거

engine.run()은 이 결과를 좌표(lat/lon) 리스트로 변환해서 반환하지만, 벤치마크 하네스는
graph edge 'length'를 직접 합산해 거리/루프폐합/잔가시/왕복겹침을 독립적으로 검증하므로
노드ID 경로가 필요하다. 그래서 run()을 그대로 쓰지 않고, run()과 동일한 순서를 재현해
좌표 변환 이전 단계의 결과를 얻는다 (엔진 알고리즘 자체는 건드리지 않음).
"""

from src.route_engine.scoring.scoring_engine import calculate_custom_score


def run_circular_engine_distance_only(engine, start_node: int, target_km: float) -> tuple[list, float]:
    """CircularGraspWaypoint{Local,Vnd,Vns}Engine 등 mode="distance" 전용 신규 엔진에서
    노드ID 경로와 실제 거리(cost, m)를 얻는다.

    기존 run_circular_engine()과 달리 calculate_custom_score()를 호출하지 않는다 —
    이 신규 엔진들은 그래프에 custom_score를 기록하지 않고 엣지 속성 length만
    직접 읽으므로(grasp_waypoint_common.py 참고) 그 계산이 불필요하다. 경로 생성에
    실패하면(빈 경로/시작 노드만 반환/잔가지 제거 후 경로 소실) ValueError를 던져
    벤치마크 하네스가 이를 status="failed" 행으로 안전하게 처리하게 한다.
    """
    nodes = engine.find_path(start_node, target_km)
    if not nodes or len(nodes) < 2:
        raise ValueError("경로 생성 실패: 유효한 순환 경로를 찾지 못했습니다 (NO_PATH)")

    pruned = engine.utils.prune_dead_ends(nodes)
    if len(pruned) < 2:
        raise ValueError("경로 생성 실패: 잔가지 제거 후 남은 경로가 없습니다")

    cost = engine.utils.calc_distance(pruned)
    return pruned, cost


def run_circular_engine(engine, start_node: int, target_km: float) -> tuple[list, float]:
    """CircularXxxEngine 인스턴스에서 노드ID 경로와 누적 custom_score(cost)를 얻는다.

    경로 생성에 실패하면(빈 경로/시작 노드만 반환/잔가지 제거 후 경로 소실) ValueError를
    던진다 — 벤치마크 하네스가 이를 status="failed" 행으로 안전하게 처리한다.
    """
    calculate_custom_score(engine.G, {
        "mode": engine.scoring_mode,
        "weights": engine.weights,
        "blocked_tags": engine.blocked_tags,
    })

    nodes = engine.find_path(start_node, target_km)
    if not nodes or len(nodes) < 2:
        raise ValueError("경로 생성 실패: 유효한 순환 경로를 찾지 못했습니다 (NO_PATH)")

    pruned = engine.utils.prune_dead_ends(nodes)
    if len(pruned) < 2:
        raise ValueError("경로 생성 실패: 잔가지 제거 후 남은 경로가 없습니다")

    _, cost = engine.utils.metrics(pruned)
    return pruned, cost
