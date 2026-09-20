"""
benchmarks/run_cache_rows_tuning.py

WaypointPoolResult의 lazy+LRU pairwise 거리 캐시 상한(pairwise_cache_rows,
기본값 256)이 논문 근거 없는 엔지니어링 기본값이라는 사실이 waypoint_pool.py와
docs/route_engine/README.md("경유지 후보 풀" 절)에 남아 있었고, 조합 단계(GRASP/ALNS)가
실제로 붙은 뒤 실측 접근 패턴으로 재튜닝하라는 TODO도 함께 남아 있었다(2026-08-30).
조합 단계는 이미 프로덕션에 연결됐지만(서비스용 순환 엔진은 CircularGraspWaypointAlnsEngine
하나로 확정 — docs/route_engine/README.md "방향 전환(turn_cost) 진단 지표" 절 실측 검증
문단 참고) 이 재튜닝은 아직 수행되지 않았다(2026-09-20 확인 — git log에 cache_rows
관련 튜닝 커밋 없음).

aggregate_by_algorithm.csv에 이미 있던 실측(100회 평균)이 재튜닝 필요성의 간접 근거다:
GRASP-Waypoint+ALNS는 elapsed_sec_mean=61.2초인데 pool_cache_misses_mean=1562.1회 —
astar_calls_mean(96.05회)보다 훨씬 커서, 시간의 상당 부분이 풀 캐시 미스(=cutoff SSSP
재계산)에 쓰일 가능성이 있다. 다만 pool_cache_hits는 aggregate_results.py::COST_METRICS에
빠져 있어 그 표만으로는 히트율을 계산할 수 없었다(주석 참고) — 이 러너가 직접 hits/misses를
같이 기록해 히트율을 낸다.

측정 대상은 프로덕션 확정 엔진 grasp-wp-alns 하나로 좁힌다(VNS/Local/VND는 운영에서
제외됨). pairwise_cache_rows 후보값을 바꿔가며 같은 (num_waypoints, target_km) 격자를
반복 실행해 pool_cache_hits/pool_cache_misses/elapsed_sec을 cache_rows별로 비교한다.

1차 스윕(cache_rows만, N=2 고정 48회)에서 64~2048 전 구간이 히트율 99.75~99.76%로
사실상 무차이였다 — "256이 부족하다"는 가설은 N=2 조건에서는 기각됐다. 다만 N=2는
GraspConfig.num_waypoints 기본값일 뿐이고 ALNS destroy/repair가 다루는 후보 수는 N에
비례해 커지므로(removal_fraction 기준 제거 개수 = ceil(N*removal_fraction)), N을 키우면
결론이 달라질 수 있다는 지적을 받아 num_waypoints를 스윕 축에 추가했다. N=3·4를 뺄
근거가 없어서(애초에 짝수만 고른 건 근거 없는 임의 선택이었다) Lewis & Corcoran(2022/2024)
논문이 검증한 n=3~8 전 구간에 현재 기본값 2를 더해 2~8 전부를 돈다.

실행: poetry run python -m benchmarks.run_cache_rows_tuning
(poetry 환경 밖 python은 버전이 달라 미세하게 다른 수치가 나올 수 있음 — analysis 기록 참고)
"""

import multiprocessing
import time

import pandas as pd

from benchmarks.benchmark import _load_default_graph, SOLVER_REGISTRY
from benchmarks.config import DEFAULT_TIME_BUDGET_SEC, RESULTS_DIR
from benchmarks.results import RESULT_COLUMNS, failed_row, run_solver_task
from benchmarks.run_metadata import save_run_metadata
from src.route_engine.scoring.scoring_engine import precompute_scoring_features
from src.route_engine.weighted_cost_runtime import attach_weighted_cost, prepare_weighted_cost

# 소형(3km)·대형(8km) 풀을 함께 봐야 한다 — waypoint_pool.py 문서 실측(2026-08-30)에서
# target_km=8이면 풀이 1.4만 개까지 커져 캐시 미스 영향이 target_km=3보다 훨씬 클 것으로
# 예상되므로, 한쪽만 보면 재튜닝 결론이 큰 target_km에서 다시 틀릴 수 있다.
TARGET_KMS = [3.0, 8.0]
# N축이 새로 들어와 조건 수가 늘어난 만큼 seed·start_node는 1개로 줄인다 — 1차 스윕에서
# seed 2개(42/7)·start_node 2개(1/175895) 간 hit_ratio 차이가 소수점 3자리 안쪽이라
# 이 축의 분산은 이미 작다고 보고 N축에 예산을 몰아준다.
SEEDS = [42]
START_NODES = [1]
# 256(현재 기본값)을 반드시 포함해 "이전 대비 얼마나 나아지는가"를 직접 비교할 수 있게 한다.
CACHE_ROWS_CANDIDATES = [64, 128, 256, 512, 1024, 2048]
# Lewis & Corcoran 논문이 검증한 n=3~8 전 구간 + 현재 프로덕션 기본값 2.
NUM_WAYPOINTS_CANDIDATES = [2, 3, 4, 5, 6, 7, 8]
ALGO = "grasp-wp-alns"
TIMEOUT_SEC = 400.0

_POOL_GRAPH = None


def _pool_worker_init():
    global _POOL_GRAPH
    _POOL_GRAPH = _load_default_graph()
    precompute_scoring_features(_POOL_GRAPH)
    attach_weighted_cost(_POOL_GRAPH, prepare_weighted_cost(
        _POOL_GRAPH, enabled=True, coverage_min_ratio=0.95,
    ))


def _pool_worker_task(start_node: int, target_km: float, seed: int, cache_rows: int, num_waypoints: int) -> dict:
    params = {
        "target_km": target_km,
        "seed": seed,
        "time_budget_sec": DEFAULT_TIME_BUDGET_SEC,
        "pairwise_cache_rows": cache_rows,
        "num_waypoints": num_waypoints,
    }
    return run_solver_task(SOLVER_REGISTRY[ALGO], _POOL_GRAPH, start_node, start_node, params)


def main():
    conditions = [
        (start_node, target_km, seed, cache_rows, num_waypoints)
        for num_waypoints in NUM_WAYPOINTS_CANDIDATES
        for cache_rows in CACHE_ROWS_CANDIDATES
        for seed in SEEDS
        for target_km in TARGET_KMS
        for start_node in START_NODES
    ]
    print(
        f"num_waypoints 후보 {len(NUM_WAYPOINTS_CANDIDATES)}개 × cache_rows 후보 "
        f"{len(CACHE_ROWS_CANDIDATES)}개 × seed {len(SEEDS)}개 × target_km {len(TARGET_KMS)}개 × "
        f"start_node {len(START_NODES)}개 = {len(conditions)}개 실행 (algo={ALGO} 고정)", flush=True,
    )

    print("워커 풀 준비 중...", flush=True)
    t0 = time.perf_counter()
    pool = multiprocessing.get_context("spawn").Pool(processes=6, initializer=_pool_worker_init)
    print(f"워커 풀 준비 완료: {time.perf_counter() - t0:.1f}초", flush=True)

    t_start = time.perf_counter()
    async_results = [
        (start_node, target_km, seed, cache_rows, num_waypoints,
         pool.apply_async(_pool_worker_task, args=(start_node, target_km, seed, cache_rows, num_waypoints)))
        for start_node, target_km, seed, cache_rows, num_waypoints in conditions
    ]

    rows = []
    out_dir = RESULTS_DIR / "waypoint_pool"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "cache_rows_tuning.csv"

    for i, (start_node, target_km, seed, cache_rows, num_waypoints, ar) in enumerate(async_results, 1):
        solver = SOLVER_REGISTRY[ALGO]
        try:
            row = ar.get(timeout=TIMEOUT_SEC)
        except multiprocessing.TimeoutError:
            row = failed_row(solver, "timeout", TIMEOUT_SEC, f"timeout after {TIMEOUT_SEC}s", target_km)
        row["seed"] = seed
        row["start_node"] = start_node
        row["pairwise_cache_rows"] = cache_rows
        row["num_waypoints_requested"] = num_waypoints
        rows.append(row)
        elapsed_total = time.perf_counter() - t_start
        hit_ratio = None
        if row.get("pool_cache_hits") is not None and row.get("pool_cache_misses") is not None:
            total = row["pool_cache_hits"] + row["pool_cache_misses"]
            hit_ratio = round(row["pool_cache_hits"] / total, 4) if total else None
        print(
            f"[{i}/{len(async_results)}] N={num_waypoints} cache_rows={cache_rows} start={start_node} "
            f"target_km={target_km} seed={seed} -> status={row['status']} "
            f"elapsed_sec={row['elapsed_sec']:.1f} pool_hits={row.get('pool_cache_hits')} "
            f"pool_misses={row.get('pool_cache_misses')} hit_ratio={hit_ratio} "
            f"(누적 {elapsed_total:.0f}s)",
            flush=True,
        )
        pd.DataFrame(
            rows, columns=["seed", "start_node", "pairwise_cache_rows", "num_waypoints_requested", *RESULT_COLUMNS],
        ).to_csv(out_path, index=False)

    pool.close()
    pool.join()

    result_df = pd.DataFrame(
        rows, columns=["seed", "start_node", "pairwise_cache_rows", "num_waypoints_requested", *RESULT_COLUMNS],
    )
    result_df.to_csv(out_path, index=False)
    meta_path = save_run_metadata(
        out_path, runner="run_cache_rows_tuning",
        seeds=SEEDS, target_kms=TARGET_KMS, start_nodes=START_NODES,
        cache_rows_candidates=CACHE_ROWS_CANDIDATES, num_waypoints_candidates=NUM_WAYPOINTS_CANDIDATES,
        algo=ALGO, workers=6, timeout_sec=TIMEOUT_SEC, time_budget_sec=DEFAULT_TIME_BUDGET_SEC,
    )

    print(f"\n전체 소요 시간: {time.perf_counter() - t_start:.1f}초")
    print(f"결과 저장 완료: {out_path}")
    print(f"메타데이터 저장 완료: {meta_path}\n")

    result_df["pool_cache_hits"] = pd.to_numeric(result_df["pool_cache_hits"], errors="coerce")
    result_df["pool_cache_misses"] = pd.to_numeric(result_df["pool_cache_misses"], errors="coerce")
    total = result_df["pool_cache_hits"] + result_df["pool_cache_misses"]
    result_df["cache_hit_ratio"] = result_df["pool_cache_hits"] / total

    print("=== num_waypoints × cache_rows별 집계 (성공 행만) ===")
    ok = result_df[result_df["status"] == "ok"]
    summary = ok.groupby(["num_waypoints_requested", "pairwise_cache_rows"]).agg(
        시도횟수=("status", "count"),
        elapsed_sec_평균=("elapsed_sec", "mean"),
        elapsed_sec_최대=("elapsed_sec", "max"),
        pool_hits_평균=("pool_cache_hits", "mean"),
        pool_misses_평균=("pool_cache_misses", "mean"),
        hit_ratio_평균=("cache_hit_ratio", "mean"),
    ).round(4)
    print(summary.to_string())


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] [%(name)s] %(message)s")
    main()
