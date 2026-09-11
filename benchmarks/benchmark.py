"""
benchmarks/benchmark.py

경유지 구축·정제 알고리즘 성능 비교를 위한 공통 벤치마크 실행기.
BasePathSolver를 상속받은 알고리즘(Strategy)들을 SOLVER_REGISTRY에 등록해두고,
CLI에서 --algo로 원하는 것만 골라 실행한다 (전체를 매번 순차 실행하지 않음).
동일한 입력(graph, start_node, target_node, params)으로 실행하고, 결과를 표로 출력 및
CSV로 저장한다. 이 프로젝트의 실제 목적("적당한 시간 내에 사용자가 원하는 순환 경로가
나오는가")에 맞춰, solver의 자기 신고(cost)를 그대로 믿지 않고 하네스가 paths/graph에서
독립적으로 재계산한 품질 지표를 함께 기록한다.

결과 행의 스키마(RESULT_COLUMNS)와 지표 계산 본체는 benchmarks/results.py에 있다 —
이 파일과 러너 4종이 같은 함수를 쓰게 해서 컬럼 누락을 구조적으로 막기 위함(2026-09-10).

하네스가 독립 계산하는 지표(전부 최종 경로 paths[0]와 graph만 본다 — 경유지 분해에
의존하지 않으므로 pruning이 경유지를 지웠는지와 무관하게 "실제로 전달되는 경로"를
서술한다):

  - within_time_budget : params['time_budget_sec'](사용자 체감 허용시간) 이내에 끝났는지.
                          timeout_sec(하드 킬 기준)과는 별개로, "기술적으로는 성공했지만
                          UX상 너무 느림"을 구분하기 위한 지표.
  - distance_km / target_km / distance_deviation_km
                        : graph의 edge 'length'(미터)를 하네스가 합산한 실제 거리와
                          params['target_km'](목표 거리) 사이의 편차.
  - is_closed_loop     : 대표 경로(paths[0])의 시작=끝 노드 여부 (순환이 실제로 닫혔는지).
  - spike_count        : 'A→B→A'처럼 갔다가 바로 되돌아오는 잔가시(삐죽 나온 길) 개수.
  - repeated_edge_ratio: 경로가 자기 구간을 재사용하는 거리 비율(거리 가중 — 구간의 두
                          번째 이후 통행분만 가산). 엔진(waypoint_route_builder.
                          edge_overlap_ratio)과 같은 함수를 쓴다. 예전 edge_overlap_ratio
                          (통행 횟수 기준)는 2026-09-02 엔진 이행 이후 정의가 어긋나
                          있어 제거했다.
  - circularity_q      : 등주 지수 4π·A/P². 완전한 원이면 1, 단순 왕복이면 0.
                          경유지와 무관한 원형성 기준값.

solver 자기 신고이며 알고리즘 간 비교에 쓰면 안 되는 컬럼:
  - cost               : wp 계열은 거리(m), 레거시 순환 계열은 누적 custom_score.
  - overlap_ratio      : 베이스 최단경로와의 겹침 비율(_oneway_engine_common.
                          base_shortest_path_overlap_ratio)로 편도 전용이다. 모든 oneway
                          solver가 같은 헬퍼를 쓰므로 그들 사이의 비교 일관성은 유지되고,
                          순환 solver는 이 값을 보고하지 않으므로 None이다.

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
    python -m benchmarks.benchmark --algo beam-wp                  # 하나만 실행
    python -m benchmarks.benchmark --algo beam-wp grasp-wp-local   # 여러 개 선택 실행
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
from benchmarks.results import (
    RESULT_COLUMNS,
    build_result_row,
    failed_row,
    validate_solver_result,
)
from benchmarks.solvers.base_solver import BasePathSolver
from benchmarks.solvers.grasp_waypoint_solver import (
    CircularGraspWaypointAlnsSolver,
    CircularGraspWaypointLocalSolver,
    CircularGraspWaypointVndSolver,
    CircularGraspWaypointVnsSolver,
)
from benchmarks.solvers.beam_waypoint_solver import CircularBeamWaypointSolver
from benchmarks.solvers.beam_waypoint_refinement_solver import (
    CircularBeamWaypointAlnsSolver,
    CircularBeamWaypointLocalSolver,
    CircularBeamWaypointVndSolver,
    CircularBeamWaypointVnsSolver,
)
from src.route_engine.scoring.scoring_engine import precompute_scoring_features

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SEC = 30.0
KILL_GRACE_SEC = 2.0  # terminate(SIGTERM) 후 kill(SIGKILL)로 넘어가기 전 대기 시간
QUEUE_FLUSH_GRACE_SEC = 5.0  # 자식 프로세스 종료 후 큐에 결과가 도착할 때까지 대기 시간

# 벤치마크 대상 알고리즘 등록 지점 (경유지 구축·정제 알고리즘만 포함).
SOLVER_REGISTRY: dict[str, BasePathSolver] = {
    "grasp-wp-local": CircularGraspWaypointLocalSolver(),
    "grasp-wp-vnd": CircularGraspWaypointVndSolver(),
    "grasp-wp-vns": CircularGraspWaypointVnsSolver(),
    "grasp-wp-alns": CircularGraspWaypointAlnsSolver(),
    "beam-wp": CircularBeamWaypointSolver(),
    "beam-wp-local": CircularBeamWaypointLocalSolver(),
    "beam-wp-vnd": CircularBeamWaypointVndSolver(),
    "beam-wp-vns": CircularBeamWaypointVnsSolver(),
    "beam-wp-alns": CircularBeamWaypointAlnsSolver(),
}

# params["seed"]를 실제로 읽는 solver (2026-09-10 코드 확인 — grasp_waypoint_solver.py와
# beam_waypoint_refinement_solver.py만 params.get("seed")를 참조한다).
# 나머지는 시드를 바꿔도 결과가 같으므로 격자에서 1회만 돌린다 — 전부 10회씩 돌리면
# 실행 시간만 늘어난다.
#
# 주의: 여기 있다고 결과가 반드시 seed마다 다르다는 뜻은 아니다. beam-wp-local /
# beam-wp-vnd는 구축(beam_search)이 결정적이고 정제(local/vnd)도 결정적 하강이라
# 실제로는 시드 불변일 수 있다 — 그건 집계에서 std≈0으로 드러난다.
SEED_SENSITIVE_SOLVERS = frozenset({
    "grasp-wp-local", "grasp-wp-vnd", "grasp-wp-vns", "grasp-wp-alns",
    "beam-wp-local", "beam-wp-vnd", "beam-wp-vns", "beam-wp-alns",
})  # 현재 registry의 모든 알고리즘


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

    행 자체를 만드는 일은 results.py::build_result_row()/failed_row()에 맡긴다 —
    이 함수가 results.py::run_solver_task()를 쓰지 않는 이유는 위 하드킬 구조 때문이며,
    "어떤 컬럼을 어떻게 채우는가"는 러너 4종과 완전히 동일하게 공유한다.
    """
    target_km = params.get("target_km")
    circular = start_node == target_node  # 순환 경로는 출발=도착

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
        return failed_row(
            solver, "failed", time.perf_counter() - wall_start,
            f"process spawn failed: {e!r}", target_km, circular,
        )

    process.join(timeout=timeout_sec)

    if process.is_alive():
        logger.warning("[%s] %.1fs 타임아웃 — 프로세스 강제 종료 후 계속 진행", solver.name, timeout_sec)
        process.terminate()  # SIGTERM
        process.join(timeout=KILL_GRACE_SEC)
        if process.is_alive():
            process.kill()  # SIGKILL — 그래도 안 죽으면 강제로
            process.join()
        return failed_row(
            solver, "timeout", time.perf_counter() - wall_start,
            f"timeout after {timeout_sec}s (process killed)", target_km, circular,
        )

    try:
        status, child_elapsed, payload = result_queue.get(timeout=QUEUE_FLUSH_GRACE_SEC)
    except queue.Empty:
        # 프로세스는 끝났는데(예: 세그폴트) 결과가 큐에 없는 경우
        logger.warning("[%s] 프로세스가 결과 없이 종료됨 (exitcode=%s)", solver.name, process.exitcode)
        return failed_row(
            solver, "failed", time.perf_counter() - wall_start,
            f"child process exited (code={process.exitcode}) without producing a result", target_km, circular,
        )

    if status == "error":
        logger.warning("[%s] 실행 실패: %s — 실패 처리 후 계속 진행", solver.name, payload)
        return failed_row(solver, "failed", child_elapsed, payload, target_km, circular)

    try:
        result = validate_solver_result(payload)
    except Exception as e:
        logger.warning("[%s] 반환값 규격 위반: %s — 실패 처리 후 계속 진행", solver.name, e)
        return failed_row(solver, "failed", child_elapsed, str(e), target_km, circular)

    return build_result_row(solver, graph, params, child_elapsed, result, circular)


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


# 정제 노브 CLI 플래그 정의. (정제, 노브, 타입, 도움말)
# 노브 이름은 grasp_waypoint_solver._REFINEMENT_PARAM_KEYS와 일치해야 하고, 정제 이름은
# waypoint_refinement.OPTIONS_AWARE_REFINEMENTS 안에 있어야 한다 — 어긋나면 엔진
# 생성자가 ValueError로 막는다. 이 일치는 test_benchmark.py::test_f1이 검사한다.
#
# alns_seed는 일부러 뺐다: ALNS 내부 난수 시드로, 실행 전체의 --seed와 다른 축이라
# 한 플래그로 섞으면 재현 조건이 모호해진다. 스윕이 필요하면 러너에서 직접 넣을 것.
_REFINEMENT_CLI_KNOBS = (
    ("alns", "iterations", int, "ALNS 최대 제거·복구 시도 수 (엔진 기본 30)"),
    ("alns", "removal_fraction", float, "한 번에 제거할 경유지 비율. 개수는 ceil(N*비율) (기본 0.3)"),
    ("alns", "start_temperature_m", float, "악화 수락 초기 척도(m) (기본 100.0)"),
    ("alns", "cooling_rate", float, "시도마다 온도에 곱하는 비율 (기본 0.95)"),
    ("alns", "segment_length", int, "연산자 가중치 갱신 주기 (기본 10)"),
    ("alns", "reaction_factor", float, "새 성과 반영률. 0이면 가중치 고정 (기본 0.2)"),
    ("alns", "candidate_limit", int, "복구 후보 풀 상한. 미지정이면 제한 없음"),
    ("alns", "max_cost_calls", int, "cost 콜백 호출 상한 (기본 3000)"),
    ("vns", "max_shake_level", int, "VNS 교란 레벨 상한. 4 이상은 전체 재구축 반복"),
)


def _add_refinement_knob_args(parser: argparse.ArgumentParser) -> None:
    for refinement, knob, value_type, help_text in _REFINEMENT_CLI_KNOBS:
        parser.add_argument(
            f"--{refinement}-{knob.replace('_', '-')}",
            dest=f"{refinement}_{knob}",
            type=value_type,
            default=None,
            help=f"[{refinement}] {help_text}",
        )


def refinement_params_from_args(args: argparse.Namespace) -> dict:
    """CLI에서 지정된 정제 노브만 골라 params 키(<정제>_<노브>)로 되돌린다.

    지정하지 않은 노브는 넣지 않는다 — 그래야 waypoint_refinement.py의 기본값이 그대로
    쓰이고, "CLI가 기본값을 덮어썼는지" 여부가 CSV/로그에서 구분된다. 이 키들은
    grasp_waypoint_solver._refinement_options_from_params()가 읽어 엔진에 전달한다.
    """
    return {
        f"{refinement}_{knob}": getattr(args, f"{refinement}_{knob}")
        for refinement, knob, _, _ in _REFINEMENT_CLI_KNOBS
        if getattr(args, f"{refinement}_{knob}", None) is not None
    }


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
    parser.add_argument(
        "--num-waypoints",
        type=int,
        default=None,
        help="GRASP/Beam이 선택할 경유지 개수(N). 미지정 시 엔진 기본값(2) 사용 — "
             "grasp-wp-*/beam-wp-* solver만 반영하며 removal_fraction 튜닝용 실험 축이다.",
    )
    _add_refinement_knob_args(parser)
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
    if args.num_waypoints is not None:
        params["num_waypoints"] = args.num_waypoints
    params.update(refinement_params_from_args(args))

    solvers = resolve_solvers(args.algo)

    if graph is not None:
        # 등록된 9종 전부 WaypointPoolGenerator.build_pool() -> compute_distance_only_lookup()
        # -> _get_feature_cache() 경로를 타므로, 캐시가 없으면 자식 프로세스마다 lazy로 다시
        # 짓는다. 부모에서 미리 채워두면 graph가 pickle될 때 캐시도 함께 건너가 그 재계산이
        # 사라진다 — 풀 기반 러너 4종의 _pool_worker_init()과 같은 모양이다.
        #
        # 구 조건은 `any(isinstance(s, OnewayAstarSolver) ...)`였는데, 2026-09-11 커밋
        # 4c7c924가 편도 solver를 SOLVER_REGISTRY에서 빼면서 import만 사라져 이 줄이
        # NameError로 남아 있었다(main()이 그래프 로드 직후 무조건 사망).
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
