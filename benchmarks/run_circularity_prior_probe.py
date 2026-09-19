"""
benchmarks/run_circularity_prior_probe.py

이슈 "구축 단계 원형성 지향 항 추가" 1단계 게이트용 격자 실행.

기존 격자(geometry_validation_results.csv 등)는 전부 num_waypoints=2다. N=2에서는 경유지가
둘뿐이라 (1) 방위각차가 원소 하나짜리 리스트이고 (2) "앞선 경유지 방위로 되돌아온다"는
전역 배치 실패가 정의조차 되지 않는다. 이 이슈가 겨냥하는 구간은 N>=4이므로 같은 격자를
num_waypoints=4로 다시 돌려, 아래 두 판정의 입력을 만든다.

  - analyze_bearing_spread.py      : 전역 배치 실패(부호 뒤집힘) 관측 여부
  - analyze_circularity_proxy.py   : 각도 지표와 circularity_q의 상관 재측정

알고리즘 선정:
    beam-wp는 정제가 없는 유일한 구축 전용 키라 "구축 단계가 만든 배치"를 그대로 본다 —
    이 이슈의 주장이 구축 단계 주장이므로 판정의 1차 근거다. GRASP에는 구축 전용 키가
    없어, 가장 가벼운 grasp-wp-local과 실제 후보인 grasp-wp-alns를 함께 돌려 정제가 배치를
    얼마나 되돌리는지까지 같이 본다.

실행:
    poetry run python -m benchmarks.run_circularity_prior_probe
"""

import multiprocessing
import time

import pandas as pd

from benchmarks.benchmark import _load_default_graph, SOLVER_REGISTRY
from benchmarks.config import BENCHMARK_SEEDS, DEFAULT_TIME_BUDGET_SEC
from benchmarks.results import RESULT_COLUMNS, failed_row, run_solver_task
from benchmarks.run_metadata import save_run_metadata
from src.route_engine.scoring.scoring_engine import precompute_scoring_features
from src.route_engine.weighted_cost_runtime import attach_weighted_cost, prepare_weighted_cost

SEEDS = BENCHMARK_SEEDS  # 러너 공용 10개
TARGET_KMS = [3.0, 5.0]
# run_geometry_validation.py와 동일한 5개 출발지 — 기존 격자와 조건을 맞춘다.
# 주의: 이 5개의 선정 기준은 기록이 없다. 결과는 "이 5개 출발지에서 관측된 값"으로만 읽는다.
START_NODE_COORDS = {
    1:      (37.564088, 126.902572),
    41417:  (37.575209, 126.928363),
    111383: (37.518967, 126.889364),
    175895: (37.596433, 127.094927),
    179044: (37.528862, 127.004334),
}
START_NODES = list(START_NODE_COORDS)
ALGOS = ["beam-wp", "grasp-wp-local", "grasp-wp-alns"]
NUM_WAYPOINTS = 4
TIMEOUT_SEC = 400.0
OUT_PATH = "benchmarks/circularity_prior_probe_results.csv"
WORKERS = 6

_POOL_GRAPH = None
# 주의: 워커가 처리하는 모든 조합이 이 전역을 재사용한다 — 그래프를 변형하는 engine을
# 추가한다면 자체 G.copy()가 있는지 확인할 것(benchmarks/benchmark.py 모듈 docstring 참고).


def _pool_worker_init():
    global _POOL_GRAPH
    _POOL_GRAPH = _load_default_graph()
    precompute_scoring_features(_POOL_GRAPH)
    # 프로덕션 dependencies.py::init_route_service()와 동일한 1회성 준비(#462) —
    # 워커가 곧바로 cost_context(WeightedEdgeCost)를 만들 수 있도록 적재율을 붙여 둔다.
    attach_weighted_cost(_POOL_GRAPH, prepare_weighted_cost(
        _POOL_GRAPH, enabled=True, coverage_min_ratio=0.95,
    ))


def _pool_worker_task(solver_key: str, start_node: int, target_km: float, seed: int) -> dict:
    """단일 (solver, start_node, target_km, seed) 조합 실행.

    결과 행 생성은 benchmarks/results.py::run_solver_task()가 전담한다.
    """
    params = {
        "target_km": target_km,
        "seed": seed,
        "time_budget_sec": DEFAULT_TIME_BUDGET_SEC,
        # 이 러너의 존재 이유. grasp-wp-*/beam-wp-* solver가 이 키를 읽는다.
        "num_waypoints": NUM_WAYPOINTS,
    }
    return run_solver_task(SOLVER_REGISTRY[solver_key], _POOL_GRAPH, start_node, start_node, params)


def main():
    conditions = [
        (algo, start_node, target_km, seed)
        for seed in SEEDS
        for target_km in TARGET_KMS
        for start_node in START_NODES
        for algo in ALGOS
    ]
    print(
        f"조건 {len(SEEDS)}seed x {len(TARGET_KMS)}target_km x {len(START_NODES)}start_node "
        f"x {len(ALGOS)}algo = {len(conditions)}개 실행 (num_waypoints={NUM_WAYPOINTS})",
        flush=True,
    )

    print("워커 풀 준비 중...", flush=True)
    t0 = time.perf_counter()
    pool = multiprocessing.get_context("spawn").Pool(processes=WORKERS, initializer=_pool_worker_init)
    print(f"워커 풀 준비 완료: {time.perf_counter() - t0:.1f}초", flush=True)

    t_start = time.perf_counter()
    async_results = [
        (algo, start_node, target_km, seed,
         pool.apply_async(_pool_worker_task, args=(algo, start_node, target_km, seed)))
        for algo, start_node, target_km, seed in conditions
    ]

    columns = ["seed", "start_node", "num_waypoints", *RESULT_COLUMNS]
    rows = []
    for i, (algo, start_node, target_km, seed, ar) in enumerate(async_results, 1):
        solver = SOLVER_REGISTRY[algo]
        try:
            row = ar.get(timeout=TIMEOUT_SEC)
        except multiprocessing.TimeoutError:
            row = failed_row(solver, "timeout", TIMEOUT_SEC, f"timeout after {TIMEOUT_SEC}s", target_km)
        row["seed"] = seed
        row["start_node"] = start_node
        row["num_waypoints"] = NUM_WAYPOINTS
        rows.append(row)
        print(
            f"[{i}/{len(async_results)}] {algo} start={start_node} target_km={target_km} seed={seed} "
            f"-> status={row['status']} elapsed_sec={row['elapsed_sec']:.1f} "
            f"(누적 {time.perf_counter() - t_start:.0f}s)",
            flush=True,
        )
        # 중간 저장 — 긴 실행이 끊겨도 여기까지의 행은 남는다(기존 러너 관례).
        pd.DataFrame(rows, columns=columns).to_csv(OUT_PATH, index=False)

    pool.close()
    pool.join()

    pd.DataFrame(rows, columns=columns).to_csv(OUT_PATH, index=False)
    meta_path = save_run_metadata(
        OUT_PATH, runner="run_circularity_prior_probe",
        seeds=SEEDS, target_kms=TARGET_KMS, start_nodes=START_NODES,
        # 노드 ID는 fixture를 다시 빌드하면 달라질 수 있어 좌표를 함께 남긴다.
        start_node_coords={str(node): coords for node, coords in START_NODE_COORDS.items()},
        algos=ALGOS, workers=WORKERS, timeout_sec=TIMEOUT_SEC,
        time_budget_sec=DEFAULT_TIME_BUDGET_SEC, num_waypoints=NUM_WAYPOINTS,
    )

    print(f"\n전체 소요 시간: {time.perf_counter() - t_start:.1f}초")
    print(f"결과 저장 완료: {OUT_PATH}")
    print(f"실행 메타데이터: {meta_path}")


if __name__ == "__main__":
    main()
