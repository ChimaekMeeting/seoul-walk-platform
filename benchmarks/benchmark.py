"""
benchmarks/benchmark.py

순환 길찾기 알고리즘 성능 비교를 위한 공통 벤치마크 실행기.
BasePathSolver를 상속받은 알고리즘(Strategy)들을 SOLVER_REGISTRY에 등록해두고,
CLI에서 --algo로 원하는 것만 골라 실행한다 (전체를 매번 순차 실행하지 않음).
동일한 입력(graph, start_node, target_node, params)으로 실행하고, 결과를 표로 출력 및
CSV로 저장한다. 이 프로젝트의 실제 목적("적당한 시간 내에 사용자가 원하는 순환 경로가
나오는가")에 맞춰, solver의 자기 신고(cost)를 그대로 믿지 않고 하네스가 paths/graph에서
독립적으로 재계산한 품질 지표를 함께 기록한다. 단 overlap_ratio는 예외로, solver가
공용 헬퍼(_oneway_engine_common.base_shortest_path_overlap_ratio)로 직접 계산해
보고한 값을 그대로 신뢰한다 

모든 oneway solver가 같은 헬퍼를 쓰므로 solver 간 비교 일관성은 유지됨:

  - within_time_budget : params['time_budget_sec'](사용자 체감 허용시간) 이내에 끝났는지.
                          timeout_sec(하드 킬 기준)과는 별개로, "기술적으로는 성공했지만
                          UX상 너무 느림"을 구분하기 위한 지표.
  - distance_km / target_km / distance_deviation_km
                        : graph의 edge 'length'(미터)를 하네스가 합산한 실제 거리와
                          params['target_km'](목표 거리) 사이의 편차.
  - is_closed_loop     : 대표 경로(paths[0])의 시작=끝 노드 여부 (순환이 실제로 닫혔는지).
  - spike_count        : 'A→B→A'처럼 갔다가 바로 되돌아오는 잔가시(삐죽 나온 길) 개수.
  - edge_overlap_ratio : 경로가 자기 자신의 구간을 재사용하는 비율 (왕복 시 같은 길을
                          그대로 공유하는 문제 검출).

알고리즘 하나가 예외를 던지거나 타임아웃되어도 나머지 알고리즘 실행과 CSV 저장은
계속 진행된다 (status/error 컬럼에 실패 사유가 기록됨). 타임아웃된 알고리즘은
스레드가 아니라 별도 OS 프로세스로 실행되므로, 진짜로 kill되어 좀비로 남지 않는다.

그래프 공유·변형 규칙(2026-08-30, G.copy() 필요 여부 재검토 이후 명시):
    solver.solve(graph, ...)에 넘기는 graph 객체가 호출마다 새로 격리되는지는
    실행 경로에 따라 다르다 — engine 구현자는 자기 engine이 어느 경로로 실행될지
    가정하지 말고, 그래프를 변형(edge/node 속성 쓰기, add_*/remove_* 등)하는 engine은
    항상 자기 __init__에서 스스로 G.copy()로 방어해야 한다.

    - benchmark.py::_run_single(): 알고리즘 1회 실행마다 별도 OS 프로세스를 새로
      띄우고, graph는 그 프로세스 경계를 넘어갈 때 pickle을 통해 자동으로 매번
      독립된 복사본이 된다 — 이 경로만 쓰면 engine이 그래프를 변형해도 다른 호출로
      새어나가지 않는다.
    - run_all_scenarios.py / run_min_separation_validation.py / run_alns_validation.py /
      run_geometry_validation.py(모두 multiprocessing.Pool 기반): _pool_worker_init()이
      워커 프로세스당 그래프를 "1번만" 로드해 전역(_POOL_GRAPH)에 두고, 그 뒤 같은
      워커가 처리하는 모든 태스크(여러 seed·start_node·target_km·algo 조합)가 그
      "같은" 객체를 재사용한다 — 매 호출 재격리가 없다. 이 경로에서 그래프를 변형하는
      engine을 새로 등록하면서 자체 G.copy() 없이 넘기면, 그 변형이 같은 워커의
      이후 호출(전혀 다른 solver·조건)에 그대로 새어나가는 버그가 된다.

    현재 SOLVER_REGISTRY 기준: circular_grasp.py/grasp_solver.py 계열(run_circular_engine()
    경유, calculate_custom_score()로 그래프에 custom_score를 실제로 써넣음)은 자기
    __init__에서 G.copy()를 한다 — 필요해서 하는 것이므로 지우면 안 된다. 반면
    grasp_waypoint_common.py 기반 4종(Local/VND/VNS/ALNS, circular_grasp_waypoint_*.py)은
    mode="distance" 전용이라 run_circular_engine_distance_only()를 쓰고
    calculate_custom_score()를 아예 안 부르며, 이 파이프라인이 실제로 쓰는 것
    (grasp_waypoint_common.py/waypoint_pool.py/PathUtils)은 전부 읽기 전용이라 __init__에서
    G.copy()를 하지 않는다(16만 노드 기준 1회 약 1.7초 절약 — VNS는 예전에 내부적으로
    VndEngine을 또 만들며 이 복사를 두 번 해서 그중 한 번은 즉시 버려졌었다). 새 engine을
    추가할 때 그래프를 변형하는 코드가 하나라도 있으면, 어느 실행 경로를 타든 안전하도록
    반드시 자체적으로 G.copy()를 넣어야 한다 — 위 풀 재사용 경로에서는 하네스가 그 실수를
    막아주지 않는다.

실행:
    python -m benchmarks.benchmark --list                  # 등록된 알고리즘 목록만 확인
    python -m benchmarks.benchmark --algo dummy-a           # 하나만 실행
    python -m benchmarks.benchmark --algo dummy-a dummy-b   # 여러 개 선택 실행
    python -m benchmarks.benchmark --algo all               # 전체 실행 (기본값)
    python -m benchmarks.benchmark --timeout 10             # solver별 제한시간(초) 조정
"""

import argparse
import logging
import multiprocessing
import queue
import time

import networkx as nx
import pandas as pd

from benchmarks.config import BENCH_DIR, ROUTE_EDGES_PARQUET, ROUTE_NODES_PARQUET
from benchmarks.solvers.alns_solver import CircularAlnsSolver, OnewayAlnsSolver
from benchmarks.solvers.base_solver import BasePathSolver
from benchmarks.solvers.beam_solver import CircularBeamSolver, OnewayBeamSolver
from benchmarks.solvers.dummy_solver import DummySolver
from benchmarks.solvers.grasp_solver import CircularGraspSolver, OnewayGraspSolver
from benchmarks.solvers.grasp_waypoint_solver import (
    CircularGraspWaypointAlnsSolver,
    CircularGraspWaypointLocalSolver,
    CircularGraspWaypointVndSolver,
    CircularGraspWaypointVnsSolver,
)
from benchmarks.solvers.beam_waypoint_solver import CircularBeamWaypointSolver
from benchmarks.solvers.plateau_solver import PlateauSolver
from benchmarks.solvers.rcsp_solver import CircularRcspSolver, OnewayRcspSolver
from benchmarks.solvers.astar_solver import OnewayAstarSolver
from benchmarks.solvers.dijkstra_solver import OnewayDijkstraSolver
from benchmarks.solvers.bi_astar_solver import OnewayBidirectionalAstarSolver
from benchmarks.solvers.bi_dijkstra_solver import OnewayBidirectionalDijkstraSolver
from src.route_engine.scoring.scoring_engine import precompute_scoring_features

logger = logging.getLogger(__name__)

RESULT_COLUMNS = [
    "algorithm", "status", "elapsed_sec", "within_time_budget",
    "cost", "overlap_ratio",
    "distance_km", "target_km", "distance_deviation_km",
    "is_closed_loop", "spike_count", "edge_overlap_ratio",
    "find_path_sec",
    "astar_calls", "cache_hits",  # 선택 필드(신규) — 기존 solver는 안 주면 None으로 채워짐
    # P2-P3 최소거리 안전장치 검증용 선택 필드(신규, grasp-wp-* solver만 채움 — 요청서 §6).
    # 기존 solver는 이 키들을 안 주므로 전부 None으로 채워지고 기존 동작은 불변이다.
    "selection_status", "feasible",
    "segment_p1_p2_m", "segment_p2_p3_m", "segment_p3_p1_m",
    "waypoint_separation_m", "min_waypoint_separation_m",
    # 원형성 진단 지표(신규, 2026-08-30 요청). repeated_edge_ratio는 모든 solver에
    # 공통(edge_overlap_ratio와 같은 값 — 하네스가 paths에서 독립 계산). waypoint_angle_diff_deg/
    # segment_balance_ratio/is_degenerate_loop는 P2/P3 개념이 있는 grasp-wp-* solver만 채운다.
    "repeated_edge_ratio", "waypoint_angle_diff_deg", "segment_balance_ratio", "is_degenerate_loop",
    "alns_operator_stats",  # grasp-wp-alns 전용 선택 필드(JSON 문자열) — 나머지는 None
    "error",
]
REQUIRED_RESULT_KEYS = ("paths", "cost")
DEFAULT_TIMEOUT_SEC = 30.0
KILL_GRACE_SEC = 2.0  # terminate(SIGTERM) 후 kill(SIGKILL)로 넘어가기 전 대기 시간
QUEUE_FLUSH_GRACE_SEC = 5.0  # 자식 프로세스 종료 후 큐에 결과가 도착할 때까지 대기 시간

# 벤치마크 대상 알고리즘 등록 지점.
SOLVER_REGISTRY: dict[str, BasePathSolver] = {
    "grasp-circular": CircularGraspSolver(),
    "grasp-oneway": OnewayGraspSolver(),
    "grasp-wp-local": CircularGraspWaypointLocalSolver(),
    "grasp-wp-vnd": CircularGraspWaypointVndSolver(),
    "grasp-wp-vns": CircularGraspWaypointVnsSolver(),
    "grasp-wp-alns": CircularGraspWaypointAlnsSolver(),
    "beam-wp": CircularBeamWaypointSolver(),
    "beam-circular": CircularBeamSolver(),
    "beam-oneway" : OnewayBeamSolver(),
    "alns-circular": CircularAlnsSolver(),
    "alns-oneway": OnewayAlnsSolver(),
    "rcsp-circular": CircularRcspSolver(),
    "rcsp-oneway": OnewayRcspSolver(),
    "plateau": PlateauSolver(),
    "astar-oneway": OnewayAstarSolver(),
    "bi-astar-oneway": OnewayBidirectionalAstarSolver(),
    "dijkstra-oneway" : OnewayDijkstraSolver(),
    "bi-dijkstra-oneway": OnewayBidirectionalDijkstraSolver(),
    "dummy-a": DummySolver(name="DummySolver-A", fake_delay_sec=0.05),
    "dummy-b": DummySolver(name="DummySolver-B", fake_delay_sec=0.1),
}


def _child_worker(solver, graph, start_node, target_node, params, result_queue) -> None:
    """별도 프로세스에서 실제로 solve()를 실행하는 함수.

    측정은 프로세스 기동(spawn) 오버헤드가 섞이지 않도록, solve() 호출 전후로만
    이 프로세스 안에서 직접 재고 그 델타만 부모에게 넘긴다.
    """
    child_start = time.perf_counter()
    try:
        raw_result = solver.solve(graph, start_node, target_node, params)
        elapsed = time.perf_counter() - child_start
        result_queue.put(("ok", elapsed, raw_result))
    except Exception as e:
        elapsed = time.perf_counter() - child_start
        result_queue.put(("error", elapsed, repr(e)))


def _validate_solver_result(result) -> dict:
    """solve() 반환값이 BasePathSolver 규격을 지키는지 검증한다.

    규격 위반은 알고리즘 버그로 간주해 예외를 던지고, 호출부(_run_single)의
    except 절에서 다른 solver를 중단시키지 않는 '실패' 행으로 변환한다.
    """
    if not isinstance(result, dict):
        raise TypeError(f"solve()는 dict를 반환해야 합니다 (실제 타입: {type(result).__name__})")

    missing = [key for key in REQUIRED_RESULT_KEYS if key not in result]
    if missing:
        raise ValueError(f"solve() 반환값에 필수 키 누락: {missing}")

    if not isinstance(result["paths"], list):
        raise TypeError(f"'paths'는 list여야 합니다 (실제 타입: {type(result['paths']).__name__})")

    if not isinstance(result["cost"], (int, float)) or isinstance(result["cost"], bool):
        raise TypeError(f"'cost'는 float(또는 int)여야 합니다 (실제 타입: {type(result['cost']).__name__})")

    overlap_ratio = result.get("overlap_ratio", 0.0)  # 명세상 기본값 0.0
    if not isinstance(overlap_ratio, (int, float)) or isinstance(overlap_ratio, bool):
        raise TypeError(f"'overlap_ratio'는 float여야 합니다 (실제 타입: {type(overlap_ratio).__name__})")

    find_path_sec = result.get("find_path_sec")  # solver가 안 주면 None (선택 항목)
    if find_path_sec is not None and (not isinstance(find_path_sec, (int, float)) or isinstance(find_path_sec, bool)):
        raise TypeError(f"'find_path_sec'는 float여야 합니다 (실제 타입: {type(find_path_sec).__name__})")

    # astar_calls/cache_hits: 신규 grasp-wp-* solver가 보고하는 진단 지표. 선택 항목이며
    # 기존 solver는 주지 않으므로 None으로 통과시킨다(기존 solver 동작 불변).
    astar_calls = result.get("astar_calls")
    if astar_calls is not None and (not isinstance(astar_calls, int) or isinstance(astar_calls, bool)):
        raise TypeError(f"'astar_calls'는 int여야 합니다 (실제 타입: {type(astar_calls).__name__})")
    cache_hits = result.get("cache_hits")
    if cache_hits is not None and (not isinstance(cache_hits, int) or isinstance(cache_hits, bool)):
        raise TypeError(f"'cache_hits'는 int여야 합니다 (실제 타입: {type(cache_hits).__name__})")

    # P2-P3 최소거리 안전장치 검증용 선택 필드(신규). grasp-wp-* solver만 채워 보내고,
    # 기존 solver는 안 주므로 전부 None으로 통과한다(기존 solver 동작 불변).
    selection_status = result.get("selection_status")
    if selection_status is not None and not isinstance(selection_status, str):
        raise TypeError(f"'selection_status'는 str이어야 합니다 (실제 타입: {type(selection_status).__name__})")
    feasible = result.get("feasible")
    if feasible is not None and not isinstance(feasible, bool):
        raise TypeError(f"'feasible'는 bool이어야 합니다 (실제 타입: {type(feasible).__name__})")

    segment_fields = {}
    for key in (
        "segment_p1_p2_m", "segment_p2_p3_m", "segment_p3_p1_m",
        "waypoint_separation_m", "min_waypoint_separation_m",
        "repeated_edge_ratio", "waypoint_angle_diff_deg", "segment_balance_ratio",
    ):
        value = result.get(key)
        if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool)):
            raise TypeError(f"'{key}'는 float(또는 int)여야 합니다 (실제 타입: {type(value).__name__})")
        segment_fields[key] = value

    is_degenerate_loop = result.get("is_degenerate_loop")
    if is_degenerate_loop is not None and not isinstance(is_degenerate_loop, bool):
        raise TypeError(f"'is_degenerate_loop'는 bool이어야 합니다 (실제 타입: {type(is_degenerate_loop).__name__})")

    alns_operator_stats = result.get("alns_operator_stats")
    if alns_operator_stats is not None and not isinstance(alns_operator_stats, str):
        raise TypeError(f"'alns_operator_stats'는 str(JSON)이어야 합니다 (실제 타입: {type(alns_operator_stats).__name__})")

    return {
        "paths": result["paths"], "cost": result["cost"], "overlap_ratio": overlap_ratio,
        "find_path_sec": find_path_sec, "astar_calls": astar_calls, "cache_hits": cache_hits,
        "selection_status": selection_status, "feasible": feasible,
        "is_degenerate_loop": is_degenerate_loop,
        "alns_operator_stats": alns_operator_stats,
        **segment_fields,
    }


def _compute_route_distance_km(graph, paths) -> float | None:
    """paths(노드 리스트들)를 따라 graph의 edge 'length'(미터)를 합산해 km로 반환한다.

    solver가 자체 신고하는 값을 그대로 믿지 않고, 하네스가 그래프 위에서 독립적으로
    재계산한다 — solver가 실제로 그래프를 따라가는 타당한 경로를 반환했는지와 무관하게
    객관적인 거리를 얻기 위함. 단위는 src/route_engine/engines/circular_rcsp.py의
    total_m / 1000 관례를 그대로 따른다(그래프 edge length는 미터, target_km은 km).

    graph에 접근할 수 없거나(None) edge에 'length'가 없으면 계산을 포기하고 None을
    반환한다 — solve() 자체는 성공했으므로 이 부가 지표 계산 실패로 전체를 실패
    처리하지는 않는다.
    """
    if graph is None or not paths:
        return None
    try:
        total_m = 0.0
        for path in paths:
            for u, v in zip(path, path[1:]):
                total_m += graph[u][v]["length"]
        return round(total_m / 1000, 4)
    except Exception:
        return None


def _is_closed_loop(paths) -> bool | None:
    """대표 경로(paths[0])의 시작 노드와 끝 노드가 같은지 — 순환이 실제로 닫혔는지의 최소 기준."""
    if not paths or len(paths[0]) < 2:
        return None
    primary_path = paths[0]
    return primary_path[0] == primary_path[-1]


def _count_spikes(paths) -> int | None:
    """대표 경로(paths[0])에서 'A→B→A'처럼 갔다가 바로 되돌아오는 잔가시(삐죽 나온 길) 개수.

    사용자 산책 경로가 막다른 길을 갔다가 되돌아 나오는 구간은 실제로 자주 지적되는
    품질 문제라, 경로 모양을 정량화하는 핵심 지표 중 하나로 둔다.
    """
    if not paths or len(paths[0]) < 3:
        return 0
    primary_path = paths[0]
    return sum(1 for i in range(len(primary_path) - 2) if primary_path[i] == primary_path[i + 2])


def _compute_edge_overlap_ratio(paths) -> float | None:
    """대표 경로(paths[0])가 자기 자신의 엣지(구간)를 얼마나 재사용하는지의 비율.

    '갈 때와 돌아올 때 같은 길을 그대로 공유'하는 문제를 solver의 자기 신고
    (overlap_ratio)에 기대지 않고 하네스가 paths에서 직접 재계산한다. 무방향
    그래프이므로 (u, v)와 (v, u)는 같은 구간으로 취급한다.

    반환값 = (2회 이상 지나간 구간의 총 통행 횟수) / (전체 구간 통행 횟수).
    """
    if not paths or len(paths[0]) < 2:
        return None
    primary_path = paths[0]
    edge_counts: dict[frozenset, int] = {}
    for u, v in zip(primary_path, primary_path[1:]):
        key = frozenset((u, v))
        edge_counts[key] = edge_counts.get(key, 0) + 1

    total_traversals = sum(edge_counts.values())
    if total_traversals == 0:
        return 0.0
    reused_traversals = sum(count for count in edge_counts.values() if count > 1)
    return round(reused_traversals / total_traversals, 4)


def _failed_row(solver: BasePathSolver, status: str, elapsed_sec: float, error: str, target_km=None) -> dict:
    return {
        "algorithm": solver.name,
        "status": status,
        "elapsed_sec": round(elapsed_sec, 6),
        "within_time_budget": None,
        "cost": None,
        "overlap_ratio": None,
        "distance_km": None,
        "target_km": target_km,
        "distance_deviation_km": None,
        "is_closed_loop": None,
        "spike_count": None,
        "edge_overlap_ratio": None,
        "find_path_sec": None,
        "astar_calls": None,
        "cache_hits": None,
        "selection_status": None,
        "feasible": None,
        "segment_p1_p2_m": None,
        "segment_p2_p3_m": None,
        "segment_p3_p1_m": None,
        "waypoint_separation_m": None,
        "min_waypoint_separation_m": None,
        "repeated_edge_ratio": None,
        "waypoint_angle_diff_deg": None,
        "segment_balance_ratio": None,
        "is_degenerate_loop": None,
        "alns_operator_stats": None,
        "error": error,
    }


def _run_single(
    solver: BasePathSolver,
    graph,
    start_node,
    target_node,
    params: dict,
    timeout_sec: float,
) -> dict:
    """solver 하나를 별도 프로세스에서 실행하고 표준화된 결과 행을 반환한다.

    스레드가 아니라 프로세스를 쓰는 이유: 스레드는 timeout이 지나도 GIL을 계속
    점유하며 백그라운드에 좀비로 남아, 이후 실행되는 다른 solver의 측정치를
    (GIL 경합으로) 왜곡시킬 수 있다. 프로세스는 timeout 시 실제로 kill()해서
    OS 차원에서 완전히 사라지므로 그런 경합이 생기지 않는다.

    부수 효과로, graph는 프로세스 경계를 넘어갈 때 pickle을 통해 자동으로 각
    프로세스마다 독립된 복사본이 되므로, solver 간 mutation 전파 문제도 별도
    처리 없이 함께 해결된다.
    """
    target_km = params.get("target_km")
    time_budget_sec = params.get("time_budget_sec")

    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()
    process = ctx.Process(
        target=_child_worker,
        args=(solver, graph, start_node, target_node, params, result_queue),
    )

    wall_start = time.perf_counter()
    try:
        process.start()
    except Exception as e:
        # solver/graph/params가 pickle이 안 되는 경우 등, 프로세스 생성 자체가 실패
        logger.warning("[%s] 프로세스 생성 실패: %s — 실패 처리 후 계속 진행", solver.name, e)
        return _failed_row(solver, "failed", time.perf_counter() - wall_start, f"process spawn failed: {e!r}", target_km)

    process.join(timeout=timeout_sec)

    if process.is_alive():
        logger.warning("[%s] %.1fs 타임아웃 — 프로세스 강제 종료 후 계속 진행", solver.name, timeout_sec)
        process.terminate()  # SIGTERM
        process.join(timeout=KILL_GRACE_SEC)
        if process.is_alive():
            process.kill()  # SIGKILL — 그래도 안 죽으면 강제로
            process.join()
        return _failed_row(
            solver, "timeout", time.perf_counter() - wall_start,
            f"timeout after {timeout_sec}s (process killed)", target_km,
        )

    try:
        status, child_elapsed, payload = result_queue.get(timeout=QUEUE_FLUSH_GRACE_SEC)
    except queue.Empty:
        # 프로세스는 끝났는데(예: 세그폴트) 결과가 큐에 없는 경우
        logger.warning("[%s] 프로세스가 결과 없이 종료됨 (exitcode=%s)", solver.name, process.exitcode)
        return _failed_row(
            solver, "failed", time.perf_counter() - wall_start,
            f"child process exited (code={process.exitcode}) without producing a result", target_km,
        )

    if status == "error":
        logger.warning("[%s] 실행 실패: %s — 실패 처리 후 계속 진행", solver.name, payload)
        return _failed_row(solver, "failed", child_elapsed, payload, target_km)

    try:
        result = _validate_solver_result(payload)
    except Exception as e:
        logger.warning("[%s] 반환값 규격 위반: %s — 실패 처리 후 계속 진행", solver.name, e)
        return _failed_row(solver, "failed", child_elapsed, str(e), target_km)

    distance_km = _compute_route_distance_km(graph, result["paths"])
    distance_deviation_km = (
        round(abs(distance_km - target_km), 4) if distance_km is not None and target_km is not None else None
    )
    within_time_budget = child_elapsed <= time_budget_sec if time_budget_sec is not None else None

    return {
        "algorithm": solver.name,
        "status": "ok",
        "elapsed_sec": round(child_elapsed, 6),
        "within_time_budget": within_time_budget,
        "cost": result["cost"],
        "overlap_ratio": result["overlap_ratio"],
        "distance_km": distance_km,
        "target_km": target_km,
        "distance_deviation_km": distance_deviation_km,
        "is_closed_loop": _is_closed_loop(result["paths"]),
        "spike_count": _count_spikes(result["paths"]),
        "edge_overlap_ratio": _compute_edge_overlap_ratio(result["paths"]),
        "find_path_sec": result.get("find_path_sec"),
        "astar_calls": result.get("astar_calls"),
        "cache_hits": result.get("cache_hits"),
        "selection_status": result.get("selection_status"),
        "feasible": result.get("feasible"),
        "segment_p1_p2_m": result.get("segment_p1_p2_m"),
        "segment_p2_p3_m": result.get("segment_p2_p3_m"),
        "segment_p3_p1_m": result.get("segment_p3_p1_m"),
        "waypoint_separation_m": result.get("waypoint_separation_m"),
        "min_waypoint_separation_m": result.get("min_waypoint_separation_m"),
        # repeated_edge_ratio는 모든 solver에 공통(요청서: "모든 벤치마크 결과에 기록").
        # grasp-wp-* solver는 route.repeated_edge_ratio를 직접 주므로 그 값을 우선 쓰고,
        # 안 주는 solver는 하네스가 paths에서 독립 계산한 edge_overlap_ratio로 채운다
        # (같은 정의의 값이라 두 경로 중 하나가 없어도 값이 빈다).
        "repeated_edge_ratio": (
            result.get("repeated_edge_ratio")
            if result.get("repeated_edge_ratio") is not None
            else _compute_edge_overlap_ratio(result["paths"])
        ),
        "waypoint_angle_diff_deg": result.get("waypoint_angle_diff_deg"),
        "segment_balance_ratio": result.get("segment_balance_ratio"),
        "is_degenerate_loop": result.get("is_degenerate_loop"),
        "alns_operator_stats": result.get("alns_operator_stats"),
        "error": "",
    }


def run_benchmark(
    solvers: list[BasePathSolver],
    graph,
    start_node,
    target_node,
    params: dict,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
) -> pd.DataFrame:
    """동일 입력으로 여러 solver를 순회 실행하고 결과를 DataFrame으로 반환한다.

    solver 하나가 실패(예외/타임아웃/규격 위반)해도 나머지 solver 실행은 계속된다.
    """
    rows = [
        _run_single(solver, graph, start_node, target_node, params, timeout_sec)
        for solver in solvers
    ]
    return pd.DataFrame(rows, columns=RESULT_COLUMNS)


def resolve_solvers(selected: list[str]) -> list[BasePathSolver]:
    """CLI로 선택된 key들을 실제 solver 리스트로 변환한다. 'all'이면 전체."""
    if "all" in selected:
        return list(SOLVER_REGISTRY.values())
    return [SOLVER_REGISTRY[key] for key in selected]


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="순환 길찾기 알고리즘 벤치마크 실행기")
    parser.add_argument(
        "-a", "--algo",
        nargs="+",
        choices=[*SOLVER_REGISTRY.keys(), "all"],
        default=["all"],
        help="실행할 알고리즘 선택 (공백으로 여러 개 지정 가능). 기본값: all",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="등록된 알고리즘 목록만 출력하고 종료",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SEC,
        help=f"solver별 제한시간(초). 초과 시 해당 solver만 실패 처리 (기본값: {DEFAULT_TIMEOUT_SEC})",
    )
    parser.add_argument(
        "--target-km",
        type=float,
        default=3.0,
        help="순환 경로 목표 거리(km) (기본값: 3.0)",
    )
    parser.add_argument(
        "--time-budget",
        type=float,
        default=None,
        help="사용자 체감 허용시간(초). 지정 시 within_time_budget 컬럼이 채워짐",
    )
    parser.add_argument(
        "--start-node",
        type=int,
        default=None,
        help="시작 노드 ID. 미지정 시 그래프에서 자동 선택",
    )
    parser.add_argument(
        "--end-node",
        type=int,
        default=None,
        help="도착 노드 ID. 미지정 시 start-node와 동일(순환 경로 기본값)",
    )
    parser.add_argument(
        "--profile",
        type=str,
        default=None,
        help="스코어링 프로필 (default/nature/safe/flat/running/landmark/child/convenient/accessible). 미지정 시 default",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="params['seed']로 전달할 난수 시드. grasp-wp-* solver만 반영(params.get('seed'))하고, "
             "기존 solver는 자체 고정 seed를 그대로 사용한다(다중 seed 비교는 신규 solver 대상).",
    )
    return parser.parse_args(argv)


def _load_default_graph() -> nx.Graph | None:
    """benchmarks/fixtures의 실제 서울 도보 그래프를 로드한다.

    fixture가 아직 빌드되지 않았으면(benchmarks/build_fixtures.py 미실행) None을 반환해
    dummy 알고리즘만으로도 하네스를 계속 사용할 수 있게 한다.
    """
    if not ROUTE_NODES_PARQUET.exists() or not ROUTE_EDGES_PARQUET.exists():
        logger.warning(
            "그래프 fixture(%s, %s)가 없습니다. 'python -m benchmarks.build_fixtures'로 먼저 생성하세요. "
            "그래프 없이 진행합니다(dummy 알고리즘만 유효).",
            ROUTE_NODES_PARQUET, ROUTE_EDGES_PARQUET,
        )
        return None

    nodes_df = pd.read_parquet(ROUTE_NODES_PARQUET)
    edges_df = pd.read_parquet(ROUTE_EDGES_PARQUET)

    graph = nx.Graph()
    for row in nodes_df.itertuples():
        graph.add_node(row.node_id, lat=row.lat, lon=row.lon)
    for row in edges_df.itertuples():
        graph.add_edge(
            row.u, row.v,
            length=row.length,
            safety_score=getattr(row, "safety_score", 0.5) or 0.5,
            nature_score=getattr(row, "nature_score", 0.5) or 0.5,
            landmark_score=getattr(row, "landmark_score", 0.0) or 0.0,
            child_score=getattr(row, "child_score", 0.0) or 0.0,
            slope_score=0.5,
        )
    return graph


def main():
    args = parse_args()

    if args.list:
        print("등록된 알고리즘:")
        for key in SOLVER_REGISTRY:
            print(f"  - {key}")
        return

    graph = _load_default_graph()

    if args.start_node is not None:
        start_node = args.start_node
    elif graph is not None:
        largest_cc = max(nx.connected_components(graph), key=len)
        start_node = sorted(largest_cc)[0]
    else:
        start_node = "A"  # dummy 알고리즘용 폴백

    target_node = args.end_node if args.end_node is not None else start_node  # 편도는 --end-node로 별도 지정
    params = {"target_km": args.target_km}
    if args.profile is not None:
        params["profile"] = args.profile
    if args.time_budget is not None:
        params["time_budget_sec"] = args.time_budget
    if args.seed is not None:
        params["seed"] = args.seed

    solvers = resolve_solvers(args.algo)

    if graph is not None and any(isinstance(s, OnewayAstarSolver) for s in solvers):
        logger.info("스코어링 feature 캐시 전처리 중...")
        precompute_scoring_features(graph)

    result_df = run_benchmark(solvers, graph, start_node, target_node, params, timeout_sec=args.timeout)

    print(result_df.to_string(index=False))

    out_path = BENCH_DIR / "benchmark_results.csv"
    result_df.to_csv(out_path, index=False)
    print(f"\n결과 저장 완료: {out_path}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] [%(name)s] %(message)s")
    main()
