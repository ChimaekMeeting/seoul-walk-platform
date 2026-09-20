"""
benchmarks/run_n_waypoint_comparison.py

운영 알고리즘(grasp-wp-alns, [[project-operating-algorithm-selection]] 2026-09-19 확정)
하나로 고정하고, 순환 경로 경유지 개수 N(2/3/4)만 바꿔가며 품질을 비교한다. 이슈 #489의
N=2 확정 결정(grasp_waypoint_common.py 주석, docs/route_engine/README.md 참고)을 뒷받침하는
재현 스크립트라 함께 커밋한다 — analysis/에 넣지 않은 이유는 AGENTS.md 기준 "새 문서가
필요한 누락 계약"이 아니라 채팅 보고 중심의 검증이기 때문이다.

거리 범위(2026-09-20 확장, 이슈 #489): 처음엔 설문 DISTANCE_MAP(SLOW/NORMAL/FAST=2/3/5km)
최댓값에 맞춰 1/3/5km만 봤으나, 실제 API 검증(`VAL-DIST-002`, dist_validator.py)은
target_km을 10km까지 허용한다 — 커스텀 입력으로 5km보다 큰 요청이 실제로 들어올 수 있어
7·9km를 추가했다. 다만 N=2/3/4 비교 자체는 1/3/5km에서 이미 N=2로 결론이 났으므로(N=4는
평균 53%·최대 81% 더 느린데 품질 이득 없음), 7·9km는 "N=2가 확정값으로도 여전히
버티는가"만 확인하면 충분하다 — N=3/4까지 다시 스윕하는 건 낭비라 7·9km는 N=2만 돈다.

출발지는 circular_density_stratified.json의 8개 중 밀도 4계층(dense/medium/sparse/rural)
대표 1곳씩(hongdae/gyeongbok/namsan/bukhan) — 과거 정제 파라미터 튜닝 스윕이 쓰던 것과 같은
4곳이다(run_density_stratified_scenarios.py 모듈 docstring 101행 참고, 원 스크립트는
2026-09-11 결론 확정 후 삭제됨). 8개 전체로 넓히는 건 이번 확장 범위 밖이다.

grasp-wp-alns는 SEED_SENSITIVE_SOLVERS라 시드 10개(BENCHMARK_SEEDS) 전부 돈다.
1/3/5km는 N 3종(4 x 3 x 3 x 10 = 360행), 7/9km는 N=2만(4 x 2 x 1 x 10 = 80행) — 총 440행.

N을 "조건"이 아니라 "비교할 값"으로 다루므로 aggregate_results.py를 그대로 못 쓴다
(그쪽은 condition_columns()가 num_waypoints를 조건 키에 넣어 N마다 다른 문제 인스턴스로
갈라버린다 — algorithm 축만 비교 대상으로 본다). 대신 조건(start_id, target_km) 단위로
시드를 접어 N 쌍(2 vs 3 / 3 vs 4 / 2 vs 4)을 benchmarks.stats.paired_permutation_test로
직접 짝짓는다 — aggregate_results.paired_tests()와 같은 방법론(짝지은 순열검정), 비교
축만 algorithm 대신 num_waypoints로 바꾼 것이다.

실행:
    poetry run python -m benchmarks.run_n_waypoint_comparison
    poetry run python -m benchmarks.run_n_waypoint_comparison --dry-run
"""

import argparse
import itertools
import json
import multiprocessing
import time
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from benchmarks.benchmark import _load_default_graph, SOLVER_REGISTRY
from benchmarks.config import (
    BENCHMARK_SEEDS, CIRCULAR_BENCHMARK_PROFILE, DATASETS_DIR, DEFAULT_TIME_BUDGET_SEC,
)
from benchmarks.results import RESULT_COLUMNS, failed_row, run_solver_task
from benchmarks.run_metadata import save_run_metadata
from benchmarks.stats import paired_permutation_test
from src.route_engine.engines.circular_grasp_waypoint_alns import GRASP_ALNS_CONFIG, GRASP_ALNS_OPTIONS
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.engines.waypoint_refinement import shared_refinement_defaults
from src.route_engine.scoring.scoring_engine import precompute_scoring_features
from src.route_engine.weighted_cost_runtime import attach_weighted_cost, prepare_weighted_cost

DATASET_PATH = DATASETS_DIR / "circular_density_stratified.json"
ALGO = "grasp-wp-alns"
START_IDS = ["hongdae", "gyeongbok", "namsan", "bukhan"]  # dense/medium/sparse/rural 1곳씩
TARGET_KMS = [1.0, 3.0, 5.0, 7.0, 9.0]  # 5.0까지는 설문 기본값, 7/9는 API 상한(10km) 대비 확장
NUM_WAYPOINTS = [2, 3, 4]
# 5.0km 이하만 N 3종 비교(결론 미확정 구간), 7/9km는 이미 확정된 N=2만 검증
# ("N=2만 검증하면 되는데...?" 2026-09-20 지적 반영 — N=3/4를 새 거리에서 다시 비교할
# 이유가 없다).
_N_COMPARE_TARGET_KMS = frozenset({1.0, 3.0, 5.0})
TIMEOUT_SEC = 90.0  # 60초 응답 예산 + 워커 경합 여유(project-operating-algorithm-selection 참고)
CHECKPOINT_EVERY = 30
OUT_PATH = "benchmarks/n_waypoint_comparison_results.csv"

_POOL_GRAPH = None


def _pool_worker_init():
    global _POOL_GRAPH
    _POOL_GRAPH = _load_default_graph()
    precompute_scoring_features(_POOL_GRAPH)
    attach_weighted_cost(_POOL_GRAPH, prepare_weighted_cost(
        _POOL_GRAPH, enabled=True, coverage_min_ratio=0.95,
    ))


def _pool_worker_task(start_node, target_km: float, num_waypoints: int, seed: int) -> dict:
    params = {
        "target_km": target_km,
        "profile": CIRCULAR_BENCHMARK_PROFILE,
        "time_budget_sec": DEFAULT_TIME_BUDGET_SEC,
        "num_waypoints": num_waypoints,
        "seed": seed,
    }
    return run_solver_task(SOLVER_REGISTRY[ALGO], _POOL_GRAPH, start_node, start_node, params)


def _load_start_points(graph) -> list[dict]:
    with open(DATASET_PATH, encoding="utf-8") as f:
        dataset = json.load(f)
    utils = PathUtils(graph)
    by_id = {sp["id"]: sp for sp in dataset["start_points"]}
    missing = [sid for sid in START_IDS if sid not in by_id]
    if missing:
        raise SystemExit(f"{DATASET_PATH}에 없는 start_id: {missing}")
    return [
        {**by_id[sid], "node": utils.find_nearest_node(by_id[sid]["lat"], by_id[sid]["lon"])}
        for sid in START_IDS
    ]


def _run(args) -> pd.DataFrame:
    graph = _load_default_graph()
    start_points = _load_start_points(graph)

    conditions = [
        {"start_id": sp["id"], "start_label": sp["label"], "tier": sp["tier"],
         "start_node": sp["node"], "target_km": km, "num_waypoints": n}
        for sp in start_points
        for km in TARGET_KMS
        for n in (NUM_WAYPOINTS if km in _N_COMPARE_TARGET_KMS else [2])
    ]
    total = len(conditions) * len(BENCHMARK_SEEDS)
    print(
        f"출발지 {len(start_points)} x 거리 {TARGET_KMS}(N 3종은 {sorted(_N_COMPARE_TARGET_KMS)}에서만) x "
        f"시드 {len(BENCHMARK_SEEDS)} = 총 {total}회 ({ALGO} 단일)",
        flush=True,
    )
    print(f"출력: {OUT_PATH}", flush=True)
    if args.dry_run:
        return pd.DataFrame()

    if Path(OUT_PATH).exists() and not args.force:
        raise SystemExit(f"출력 파일이 이미 있습니다: {OUT_PATH} (덮어쓸 의도면 --force)")

    print("워커 풀 준비 중...", flush=True)
    t0 = time.perf_counter()
    pool = multiprocessing.get_context("spawn").Pool(processes=args.workers, initializer=_pool_worker_init)
    print(f"워커 풀 준비 완료: {time.perf_counter() - t0:.1f}초", flush=True)

    t_start = time.perf_counter()
    async_results = [
        (cond, seed, pool.apply_async(
            _pool_worker_task,
            args=(cond["start_node"], cond["target_km"], cond["num_waypoints"], seed),
        ))
        for cond in conditions
        for seed in BENCHMARK_SEEDS
    ]

    # target_km은 RESULT_COLUMNS에 이미 있다 — 여기서 다시 넣으면 동명 컬럼이 중복돼
    # df["target_km"]이 Series 대신 DataFrame이 되고 groupby가 깨진다(2026-09-20 실측 확인).
    columns = ["start_id", "start_label", "tier", "num_waypoints", "seed", *RESULT_COLUMNS]
    solver = SOLVER_REGISTRY[ALGO]
    rows = []
    for i, (cond, seed, ar) in enumerate(async_results, 1):
        try:
            row = ar.get(timeout=TIMEOUT_SEC)
        except multiprocessing.TimeoutError:
            row = failed_row(solver, "timeout", TIMEOUT_SEC, f"timeout after {TIMEOUT_SEC}s",
                              cond["target_km"], circular=True)
        row["start_id"] = cond["start_id"]
        row["start_label"] = cond["start_label"]
        row["tier"] = cond["tier"]
        row["target_km"] = cond["target_km"]
        row["num_waypoints"] = cond["num_waypoints"]
        row["seed"] = seed
        rows.append(row)

        if i % CHECKPOINT_EVERY == 0 or i == len(async_results):
            print(f"[{i}/{len(async_results)}] 누적 {time.perf_counter() - t_start:.0f}s", flush=True)
            pd.DataFrame(rows, columns=columns).to_csv(OUT_PATH, index=False)

    pool.close()
    pool.join()

    result_df = pd.DataFrame(rows, columns=columns)
    meta_path = save_run_metadata(
        OUT_PATH, runner="run_n_waypoint_comparison",
        algo=ALGO, start_ids=START_IDS, target_kms=TARGET_KMS, num_waypoints=NUM_WAYPOINTS,
        seeds=BENCHMARK_SEEDS,
        algorithm_defaults={"config": asdict(GRASP_ALNS_CONFIG), "alns_options": dict(GRASP_ALNS_OPTIONS)},
        refinement_defaults=shared_refinement_defaults(),
        workers=args.workers, timeout_sec=TIMEOUT_SEC, time_budget_sec=DEFAULT_TIME_BUDGET_SEC,
        circular_profile=CIRCULAR_BENCHMARK_PROFILE,
    )
    print(f"\n전체 소요 시간: {time.perf_counter() - t_start:.1f}초")
    print(f"결과 저장 완료: {OUT_PATH}")
    print(f"메타데이터 저장 완료: {meta_path}\n")
    return result_df


def _summarize(df: pd.DataFrame) -> None:
    ok = df[df["status"] == "ok"].copy()

    print("=== N별 게이트 통과율·소요시간 (전체) ===")
    overall = df.groupby("num_waypoints").agg(
        시도횟수=("status", "count"),
        성공=("status", lambda s: (s == "ok").sum()),
        게이트통과율=("passed", lambda s: s.mean() if s.notna().any() else None),
        평균초=("elapsed_sec", "mean"),
        최대초=("elapsed_sec", "max"),
    ).round(4)
    print(overall.to_string())

    print("\n=== N x 거리별 게이트 통과율 ===")
    by_dist = df.groupby(["target_km", "num_waypoints"]).agg(
        게이트통과율=("passed", lambda s: s.mean() if s.notna().any() else None),
        거리편차평균=("distance_deviation_km", "mean"),
        재통행률평균=("repeated_edge_ratio", "mean"),
    ).round(4)
    print(by_dist.to_string())

    # 조건(start_id, target_km) 단위로 시드를 접은 뒤 N 쌍을 짝지은 순열검정.
    condition_metric = ok.groupby(["start_id", "target_km", "num_waypoints"]).agg(
        distance_deviation_km=("distance_deviation_km", "mean"),
        repeated_edge_ratio=("repeated_edge_ratio", "mean"),
    ).reset_index()

    print(
        f"\n[짝지은 비교] {len(START_IDS)}출발지 x {len(TARGET_KMS)}거리 = "
        f"{len(START_IDS) * len(TARGET_KMS)}개 조건에서 시드 평균을 낸 뒤 N을 짝짓습니다."
    )
    for metric in ("distance_deviation_km", "repeated_edge_ratio"):
        pivot = condition_metric.pivot_table(
            index=["start_id", "target_km"], columns="num_waypoints", values=metric,
        )
        print(f"\n=== {metric}: N 쌍별 짝지은 순열검정 ===")
        rows = []
        for left, right in itertools.combinations(NUM_WAYPOINTS, 2):
            if left not in pivot.columns or right not in pivot.columns:
                continue
            pair = pivot[[left, right]].dropna()
            p_value, n, mean_difference = paired_permutation_test(pair[left] - pair[right])
            rows.append({
                "N_A": left, "N_B": right, "n_conditions": n,
                "평균차(A-B)": mean_difference, "p_value": p_value,
                "유의(α=0.05)": "예" if p_value is not None and p_value < 0.05 else "아니오",
            })
        print(pd.DataFrame(rows).round(6).to_string(index=False) if rows else "(해당 없음)")

    print(
        "\n[주의] p_value는 비교가 3쌍이라 다중비교 보정 없이는 그대로 읽지 말 것"
        "(Bonferroni 보정선 α=0.05/3=0.0167). n_conditions는 최대 12(4출발지 x 3거리)."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="실행하지 않고 총 실행 수만 계산")
    parser.add_argument("--force", action="store_true", help="출력 CSV가 있어도 덮어쓴다")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    df = _run(args)
    if args.dry_run or df.empty:
        return
    _summarize(df)


if __name__ == "__main__":
    import logging
    import sys
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] [%(name)s] %(message)s")
    main()
