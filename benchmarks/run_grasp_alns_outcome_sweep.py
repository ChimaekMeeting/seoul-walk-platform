"""
benchmarks/run_grasp_alns_outcome_sweep.py

grasp-wp-alns에서 ALNS 제안이 최종 경로에 채택되는지, 버려진다면 왜 버려지는지를 밀도 층화
데이터셋 전 조건에서 확인한다. 7km·N=4 확인(run_grasp_alns_candidate_limit_check.py)에서
60회 모두 ALNS가 채택되지 않았고 alns_candidate_limit {2,8,16}의 품질이 끝자리까지 같았다.
그 결과가 다른 거리·N에서도 유지되는지 보고, waypoint_refinement.py::alns()가 남기는
outcome_counts(ALNS_OUTCOMES)·comparison_decided_by로 기각 사유를 분리한다.

격자: 밀도 층화 데이터셋의 8개 출발지 x target_kms {1,3,5,7,9} x N {2,3,4}
      x BENCHMARK_SEEDS 10개 x alns_candidate_limit {2, 16} = 2,400회.
      TUNED_KNOBS(alns_iterations=10, rcl_size=16, angle_diversity_weight_m=0.0)는 고정.
      16은 엔진 기본 동작(candidate_limit=cfg.rcl_size)과 같은 값을 명시한 것이고,
      2는 N<=4에서 remove_count(최대 2) 이상인 하한이다.

실행 순서: 시드 앞 5개로 전 조건을 한 바퀴 돈 뒤 뒤 5개를 돈다 — 중간에 멈춰도 앞 바퀴는
조건 균형이 맞는 완결 표본으로 남는다.

중단 복구: 결과 CSV는 CHECKPOINT_EVERY행마다 저장된다. 같은 명령에 --resume을 붙이면
이미 기록된 (출발지, 거리, N, 시드, 값) 조합을 건너뛰고 이어서 돈다.

실행:
    poetry run python -m benchmarks.run_grasp_alns_outcome_sweep --dry-run
    poetry run python -m benchmarks.run_grasp_alns_outcome_sweep
    poetry run python -m benchmarks.run_grasp_alns_outcome_sweep --resume
"""

import argparse
import itertools
import json
import multiprocessing
import sys
import time
from pathlib import Path

import pandas as pd

from benchmarks.benchmark import _load_default_graph, SOLVER_REGISTRY
from benchmarks.config import BENCHMARK_SEEDS, DEFAULT_TIME_BUDGET_SEC
from benchmarks.results import RESULT_COLUMNS, failed_row, run_solver_task
from benchmarks.run_density_stratified_scenarios import TUNED_KNOBS, _load_dataset
from benchmarks.run_metadata import save_run_metadata
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.engines.waypoint_refinement import ALNS_OUTCOMES
from src.route_engine.scoring.scoring_engine import precompute_scoring_features

ALGO = "grasp-wp-alns"
PARAM = "alns_candidate_limit"
VALUES = [2, 16]
SEED_PASSES = [BENCHMARK_SEEDS[:5], BENCHMARK_SEEDS[5:]]

TIMEOUT_SEC = 600.0
CHECKPOINT_EVERY = 20
OUT_PATH = "benchmarks/grasp_alns_outcome_sweep_results.csv"
KEY_COLUMNS = ["start_id", "target_km", "num_waypoints", "seed", "value"]
COMPARE_KEYS = ("feasibility", "repeated_edge_ratio", "distance_error_m", "equal")

_POOL_GRAPH = None


def _pool_worker_init():
    global _POOL_GRAPH
    _POOL_GRAPH = _load_default_graph()
    precompute_scoring_features(_POOL_GRAPH)


def _pool_worker_task(value: int, start_node, target_km: float, num_waypoints: int, seed: int) -> dict:
    params = {
        "target_km": target_km, "num_waypoints": num_waypoints,
        "time_budget_sec": DEFAULT_TIME_BUDGET_SEC, "seed": seed,
        **TUNED_KNOBS.get(ALGO, {}),
        PARAM: value,
    }
    return run_solver_task(SOLVER_REGISTRY[ALGO], _POOL_GRAPH, start_node, start_node, params)


def _alns_fields(raw) -> dict:
    """alns_operator_stats JSON을 분석용 평면 컬럼으로 편다."""
    fields = {
        "alns_calls": None, "alns_cost_calls": None, "alns_accepted_moves": None,
        "winner_alns_accepted": None, "winner_outcome": None,
        **{f"oc_{name}": None for name in ALNS_OUTCOMES},
        **{f"nb_{key}": None for key in COMPARE_KEYS},
        **{f"acc_{key}": None for key in COMPARE_KEYS},
    }
    if not isinstance(raw, str) or not raw:
        return fields
    stats = json.loads(raw)
    winner = stats.get("winning_iteration") or {}
    outcomes = stats.get("outcome_counts") or {}
    decided = stats.get("comparison_decided_by") or {}
    fields.update({
        "alns_calls": stats.get("alns_calls"),
        "alns_cost_calls": stats.get("total_cost_calls"),
        "alns_accepted_moves": stats.get("total_accepted_moves"),
        "winner_alns_accepted": winner.get("accepted"),
        "winner_outcome": winner.get("outcome"),
        **{f"oc_{name}": outcomes.get(name, 0) for name in ALNS_OUTCOMES},
        **{f"nb_{key}": decided.get("not_better", {}).get(key, 0) for key in COMPARE_KEYS},
        **{f"acc_{key}": decided.get("accepted", {}).get(key, 0) for key in COMPARE_KEYS},
    })
    return fields


def _keep_system_awake() -> None:
    """Windows 유휴 절전을 이 프로세스가 살아 있는 동안만 막는다(시스템 설정은 바꾸지 않음).
    덮개 닫기·수동 절전은 막지 못한다."""
    if sys.platform != "win32":
        return
    import ctypes
    es_continuous, es_system_required = 0x80000000, 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(es_continuous | es_system_required)


def _conditions(dataset: dict) -> list[dict]:
    starts = dataset["start_points"]
    ordered = []
    for seeds in SEED_PASSES:
        for target_km, n, sp, seed, value in itertools.product(
            dataset["target_kms"], dataset["num_waypoints"], starts, seeds, VALUES,
        ):
            ordered.append({
                "start_id": sp["id"], "tier": sp["tier"], "lat": sp["lat"], "lon": sp["lon"],
                "target_km": float(target_km), "num_waypoints": int(n), "seed": int(seed), "value": int(value),
            })
    return ordered


def _key(row) -> tuple:
    return (row["start_id"], float(row["target_km"]), int(row["num_waypoints"]), int(row["seed"]), int(row["value"]))


def _summarize(df: pd.DataFrame) -> None:
    ok = df[df["status"] == "ok"].copy()
    print(f"\n상태 분포: {df['status'].value_counts().to_dict()}")
    if ok.empty:
        return
    # --resume으로 CSV를 다시 읽으면 bool 컬럼이 문자열로 올 수 있어 명시적으로 맞춘다.
    for col in ("winner_alns_accepted", "passed"):
        ok[col] = ok[col].map(lambda v: str(v) == "True")

    print("\n=== 최종 경로가 ALNS 결과인 비율 (target_km x N, 두 값 합산) ===")
    print(ok.pivot_table(index="target_km", columns="num_waypoints",
                         values="winner_alns_accepted", aggfunc="mean").round(3).to_string())

    oc_cols = [f"oc_{name}" for name in ALNS_OUTCOMES]
    print("\n=== alns() 호출 결과 사유 분포 (target_km별 합계 대비 비율) ===")
    by_km = ok.groupby("target_km")[oc_cols].sum()
    print(by_km.div(by_km.sum(axis=1), axis=0).round(3).to_string())

    print("\n=== not_better 기각에서 승패를 가른 비교 키 (target_km별 합계) ===")
    print(ok.groupby("target_km")[[f"nb_{k}" for k in COMPARE_KEYS]].sum().to_string())

    print("\n=== accepted에서 이긴 비교 키 (target_km별 합계) ===")
    print(ok.groupby("target_km")[[f"acc_{k}" for k in COMPARE_KEYS]].sum().to_string())

    print(f"\n=== {PARAM}별 품질·비용 (target_km별) ===")
    print(ok.groupby(["target_km", "value"]).agg(
        n=("status", "count"), 게이트통과율=("passed", "mean"), 평균cost=("cost", "mean"),
        평균ALNS비용호출=("alns_cost_calls", "mean"), 평균초=("elapsed_sec", "mean"),
    ).round(3).to_string())

    pair_keys = ["start_id", "target_km", "num_waypoints", "seed"]
    wide = ok.pivot_table(index=pair_keys, columns="value", values="cost", aggfunc="first").dropna()
    if not wide.empty and len(VALUES) == 2:
        same = (wide[VALUES[0]] == wide[VALUES[1]])
        print(f"\n짝 비교: 두 값의 cost가 완전히 같은 조건 {int(same.sum())}/{len(wide)}")
        diff = wide[~same].reset_index()
        if not diff.empty:
            print(diff.head(30).to_string())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true", help="기존 결과 CSV의 완료 조합을 건너뛰고 이어서 실행")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    dataset = _load_dataset()
    conditions = _conditions(dataset)

    prior = pd.DataFrame()
    if Path(OUT_PATH).exists():
        if not args.resume:
            raise SystemExit(f"출력 파일이 이미 있습니다: {OUT_PATH}\n이어서 돌리려면 --resume, 새로 돌리려면 파일을 옮기세요.")
        prior = pd.read_csv(OUT_PATH)
    done = {_key(r) for _, r in prior.iterrows()} if not prior.empty else set()
    pending = [c for c in conditions if _key(c) not in done]

    print(f"{ALGO} / {PARAM} {VALUES}: 출발지 {len(dataset['start_points'])} x 거리 {dataset['target_kms']} x "
          f"N {dataset['num_waypoints']} x 시드 {len(BENCHMARK_SEEDS)} x 값 {len(VALUES)} = 총 {len(conditions)}회 "
          f"(완료 {len(done)}, 남음 {len(pending)}) 고정 {TUNED_KNOBS.get(ALGO)}", flush=True)
    if args.dry_run or not pending:
        return

    _keep_system_awake()
    graph = _load_default_graph()
    utils = PathUtils(graph)
    nodes = {sp["id"]: utils.find_nearest_node(sp["lat"], sp["lon"]) for sp in dataset["start_points"]}

    print("워커 풀 준비 중...", flush=True)
    pool = multiprocessing.get_context("spawn").Pool(processes=args.workers, initializer=_pool_worker_init)

    t_start = time.perf_counter()
    async_results = [
        (cond, pool.apply_async(_pool_worker_task, args=(
            cond["value"], nodes[cond["start_id"]], cond["target_km"], cond["num_waypoints"], cond["seed"])))
        for cond in pending
    ]

    # target_km은 RESULT_COLUMNS에도 있다 — 앞에 또 적으면 헤더가 중복돼 _summarize()의
    # pivot_table이 "Grouper for 'target_km' not 1-dimensional"로 죽는다(2026-09-15 실측).
    columns = ["start_id", "tier", "param", "value", "num_waypoints", "seed", "seed_pass",
               *RESULT_COLUMNS, *_alns_fields(None).keys()]
    assert len(columns) == len(set(columns)), "결과 컬럼 이름이 중복됐습니다"
    rows = prior.to_dict("records") if not prior.empty else []
    seed_pass = {seed: i + 1 for i, seeds in enumerate(SEED_PASSES) for seed in seeds}

    for i, (cond, ar) in enumerate(async_results, 1):
        try:
            row = ar.get(timeout=TIMEOUT_SEC)
        except multiprocessing.TimeoutError:
            row = failed_row(SOLVER_REGISTRY[ALGO], "timeout", TIMEOUT_SEC, f"timeout after {TIMEOUT_SEC}s",
                             cond["target_km"], circular=True)
        except Exception as e:  # 워커 예외 1건이 전체 무인 실행을 끝내지 않게 한다
            row = failed_row(SOLVER_REGISTRY[ALGO], "failed", 0.0, repr(e), cond["target_km"], circular=True)
        row.update(_alns_fields(row.get("alns_operator_stats")))
        row.update({
            "start_id": cond["start_id"], "tier": cond["tier"], "param": PARAM, "value": cond["value"],
            "target_km": cond["target_km"], "num_waypoints": cond["num_waypoints"], "seed": cond["seed"],
            "seed_pass": seed_pass[cond["seed"]],
        })
        rows.append(row)

        if i % CHECKPOINT_EVERY == 0 or i == len(async_results):
            elapsed = time.perf_counter() - t_start
            eta = elapsed / i * (len(async_results) - i)
            print(f"[PROGRESS {i}/{len(async_results)}] 누적 {elapsed / 60:.1f}분, 남은 예상 {eta / 60:.0f}분 "
                  f"(현재 {cond['target_km']}km N={cond['num_waypoints']} pass {seed_pass[cond['seed']]})", flush=True)
            pd.DataFrame(rows, columns=columns).to_csv(OUT_PATH, index=False)

    pool.close()
    pool.join()

    result_df = pd.DataFrame(rows, columns=columns)
    meta_path = save_run_metadata(
        OUT_PATH, runner="run_grasp_alns_outcome_sweep",
        algo=ALGO, param=PARAM, values=VALUES, fixed_knobs=TUNED_KNOBS.get(ALGO),
        start_points=dataset["start_points"], target_kms=dataset["target_kms"],
        num_waypoints=dataset["num_waypoints"], seed_passes=SEED_PASSES,
        workers=args.workers, timeout_sec=TIMEOUT_SEC, time_budget_sec=DEFAULT_TIME_BUDGET_SEC,
        resumed_rows=len(prior),
    )

    print(f"\n전체 소요 시간: {(time.perf_counter() - t_start) / 60:.1f}분")
    print(f"결과 저장 완료: {OUT_PATH}")
    print(f"메타데이터 저장 완료: {meta_path}")
    _summarize(result_df)
    print("\nSWEEP_DONE", flush=True)


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] [%(name)s] %(message)s")
    main()
