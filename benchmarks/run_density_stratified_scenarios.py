"""
benchmarks/run_density_stratified_scenarios.py

밀도 층화 순환 경로 시나리오 러너 (2026-09-12, 이슈: 순환 경로 벤치마크 시나리오 확장).

기존 run_all_scenarios.py는 datasets/route_engine.json의 flat scenario 목록만 읽고
params에 num_waypoints를 넣지 않아(run_all_scenarios.py:151-155) 전 시나리오가 엔진
기본값 N=2로 고정돼 있었다. 이 러너는 별도 데이터셋
(datasets/circular_density_stratified.json)의 start_points x target_kms x
num_waypoints 곱집합을 돈다 — route_engine.json과 그 소비자(run_all_scenarios.py)는
건드리지 않는다.

두 단계로 나눠 돈다(--stage로 선택):
    1단계(탐색): 전 알고리즘 시드 1회(BENCHMARK_SEEDS[0]). 실행 가능 영역 지도, 게이트
                  임계값 분포, 퇴화 사례 수집이 목적. 여기서 이상 없음을 확인한 뒤
                  2단계로 넘어간다.
    2단계(본실행): SEED_SENSITIVE_SOLVERS는 BENCHMARK_SEEDS 10개 전부, 그 외(beam-wp)는
                  1회만(run_all_scenarios.py::_scenario_tasks와 동일 규칙).
                  장시간 실행이므로 CHECKPOINT_EVERY마다 중간 저장한다
                  (run_alns_sweep.py:39 패턴).

좌표만 두고 node_id를 저장하지 않는 이유: fixture를 다시 빌드하면 노드 ID는 달라지지만
좌표는 그대로이므로, PathUtils.find_nearest_node()로 실행 시점에 해석하는 편이
재현성이 높다.

실행:
    python -m benchmarks.run_density_stratified_scenarios --stage 1
    python -m benchmarks.run_density_stratified_scenarios --stage 2
    python -m benchmarks.run_density_stratified_scenarios --stage 2 --dry-run   # 실행 수만 계산

부분 재실행:
    알고리즘별 기본값(circular_grasp_waypoint_alns.py의 GRASP_ALNS_CONFIG·GRASP_ALNS_OPTIONS,
    circular_beam_waypoint_vns.py의 BEAM_VNS_CONFIG)이 바뀌면 값이 실제로 달라진 알고리즘만
    다시 돌리면 된다 — 나머지 행은 같은 설정으로 이미 돈 결과라 재사용할 수 있다.

    기존 CSV의 설정 이력: 2026-09-13 02:39 1단계 실행분은 튜닝 전 엔진 기본값이었다(노브 주입
    커밋 1704ee3은 같은 날 18:22). 그 뒤 확정값은 이 러너의 TUNED_KNOBS로 params에 주입하다가
    엔진 알고리즘별 기본값으로 옮겼다 — 옮기기 전후 솔버에 실리는 설정은 같다. 튜닝 전 기본값과
    실제로 달라진 것은 grasp-wp-alns 4종(alns_iterations 30->10, rcl_size 8->16,
    angle_diversity_weight_m 1500.0->0.0, alns_candidate_limit 8->2)과 beam-wp-vns의
    beam_width(8->4)뿐이다. alns_candidate_limit은 따로 주지 않으면 rcl_size를 따라간다
    (waypoint_refinement.py::_alns_config). beam-wp-alns의 beam_width=8은 공용 기본값
    (DEFAULT_CONFIG.rcl_size)과 같아 동작이 바뀌지 않는다.

    alns_candidate_limit=2 반영(2026-09-15, #434) 이후 density_stratified_stage1_retuned.csv의
    grasp-wp-alns 행은 한도 16(rcl_size 연동)으로 돈 결과라 재사용할 수 없다. 같은 파일의
    beam-wp-vns 행은 설정이 그대로라 재사용한다.

    python -m benchmarks.run_density_stratified_scenarios --stage 1 \
        --algos grasp-wp-alns --out benchmarks/density_stratified_stage1_climit2.csv

    부분 실행 CSV는 나중에 재사용분과 합쳐야 하고, 합친 뒤에는 집계를 전부 다시 내야 한다
    — circularity_q_rel 같은 상대지표의 분모가 CSV 안의 알고리즘 조합에 의존하기 때문이다
    (aggregate_results.py 참고).
"""

import argparse
import itertools
import json
import multiprocessing
import time
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from benchmarks.benchmark import _load_default_graph, SEED_SENSITIVE_SOLVERS, SOLVER_REGISTRY
from benchmarks.config import (
    BENCHMARK_SEEDS, CIRCULAR_BENCHMARK_PROFILE, DATASETS_DIR, DEFAULT_TIME_BUDGET_SEC,
)
from benchmarks.results import RESULT_COLUMNS, failed_row, run_solver_task
from benchmarks.run_metadata import save_run_metadata
from src.route_engine.engines.circular_beam_waypoint_vns import BEAM_VNS_CONFIG
from src.route_engine.engines.circular_grasp_waypoint_alns import GRASP_ALNS_CONFIG, GRASP_ALNS_OPTIONS
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.scoring.scoring_engine import precompute_scoring_features

DATASET_PATH = DATASETS_DIR / "circular_density_stratified.json"

# beam/grasp-waypoint 9종 중 8종 — run_all_scenarios.py::CIRCULAR_ALGOS에서 grasp-wp-vns만
# 뺀 목록. 2026-09-13 1단계 실측(density_stratified_stage1_results.csv)에서
# GRASP-Waypoint+VNS가 전체 소요시간의 57.9%를 차지하고 9km+N>=3 16개 조건 전부가 600초
# 타임아웃이었다 — waypoint_refinement.py::vns_loop()가 "개선되면 shake_level을 1로 리셋"
# 구조라 반복 횟수 상한이 없고(ALNS의 alns_iterations 같은 자체 종료 조건이 없음), 반복당
# 비용도 N에 비례해 커져 N을 늘리자 조합적으로 폭증했다(사용자 확인 후 제외 결정).
# Beam-Waypoint+VNS는 같은 VNS이지만 속도(평균 38.4초)와 게이트통과율(0.892, 최고 동률)이
# 둘 다 좋아 그대로 유지한다 — GRASP 쪽 vns_loop()의 반복 무제한 구조가 원인이지 VNS
# 자체가 문제는 아니다.
ALGOS = [
    "grasp-wp-local", "grasp-wp-vnd", "grasp-wp-alns",
    "beam-wp", "beam-wp-local", "beam-wp-vnd", "beam-wp-vns", "beam-wp-alns",
]

# 정제 파라미터 튜닝 스윕 결론(2026-09-13, run_refinement_tuning_sweep.py 청크 A/B1/B2/B3,
# 튜닝 집합 홍대/경복궁/남산/북한산 x {3,7}km x N=4, 통계 검정 근거는 대화 기록 참고).
# 공용 기본값과 달라진 확정값은 엔진 쪽 알고리즘별 상수로 옮겼다(_ALGORITHM_DEFAULTS 참고 —
# 값과 근거의 원본은 src/). 아래는 튜닝했지만 기본값 유지로 확정된 노브다 — 명시하지 않는
# 것 자체가 의도적 선택이다:
#   - beam-wp-alns.beam_width: 8(공용 기본값)이 4(p<0.0001)·16(p=0.0005)보다 게이트통과율에서
#     유의미하게 우수. beam-wp-vns(4)와 값이 다른 것은 기준이 달라서다 — Beam+ALNS는 ALNS
#     제안이 최종 경로로 거의 채택되지 않아(폭 8에서 1/240) 구축 품질이 곧 결과이고 폭 16까지도
#     중앙값 11.5초로 싸서 품질로 골랐다. VNS 쪽 기준은 circular_beam_waypoint_vns.py 참고.
#   - beam-wp.beam_width: n=8(튜닝 집합)에서 과소검정 의심돼 n=40(전체 8출발지 x 5거리)으로
#     확장 재검정했으나 여전히 무효(모든 쌍 p>=0.25) — 데이터 부족이 아니라 무효 확정.
#   - beam-wp-alns.alns_removal_fraction: n=240, 무효(p>=0.68).
#   - beam-wp-vns.vns_max_shake_level: n=240, 무효(p>=0.13, 모든 beam_width에서 동일).
#   - grasp-wp-local.rcl_size, grasp-wp-vnd.rcl_size: 2026-09-14 구축 파라미터 튜닝
#     (run_grasp_rcl_size_tuning.py, 7km, n=40/값)에서 기존 기본값(8)이 이미 최선으로
#     확인됨 — 4는 8보다 거리편차 유의미하게 나쁘고(p<0.005), 16은 8과 통계적으로 동급
#     이면서 더 비쌈(특히 vnd는 12가 8과 동급인데 거의 2배 비쌈, p=0.299).
#   - grasp-wp-alns.distance_tolerance_ratio: n=40/값, 무효(모든 쌍 p>=0.11) — 기본값
#     0.05가 숫자상 가장 높지만(0.625) 통계적으로 확정 못 함.
#   - grasp-wp-alns.grasp_iters: 24 vs 48이 무효(p=0.143, 통계적으로 동급)인데 48은
#     거의 2배 비쌈(101초→190초) — 8은 24·48 모두보다 유의미하게 나빠 기존 기본값(24)
#     유지.
#   - min_waypoint_separation_ratio: 스크리닝 단일 샘플(seed=42)에서 grasp-wp-alns와
#     beam-wp-vns가 정반대 방향 신호를 보여 미해결로 남겼으나, 240회 통계 검증
#     (run_min_waypoint_separation_tuning.py, 2026-09-14)으로 노이즈였음을 확인 —
#     beam-wp-vns는 완전 무효(모든 쌍 p>=0.15), grasp-wp-alns는 0.05·0.20(기본값)이
#     완전히 동일(p=1.0)하고 0.40만 유의미하게 나쁨(p<0.0001). 두 알고리즘 다 기존
#     기본값(0.20) 유지로 확정.
# 공용 기본값과 다른 확정값을 쓰는 알고리즘 → 그 솔버가 기준으로 삼는 엔진 쪽 상수.
# 값을 여기 다시 적지 않는다(원본은 src/) — 메타데이터 기록과 테스트 대조에만 쓴다.
_ALGORITHM_DEFAULTS = {
    "grasp-wp-alns": {"config": GRASP_ALNS_CONFIG, "alns_options": GRASP_ALNS_OPTIONS},
    "beam-wp-vns": {"config": BEAM_VNS_CONFIG},
}


def algorithm_defaults(algos) -> dict:
    """algos 중 알고리즘별 확정 기본값을 쓰는 것만 골라 JSON으로 남길 수 있게 편다.

    어떤 설정으로 돈 실행인지는 행만 보고 판정할 수 없어(노브는 결과 컬럼에 안 들어간다)
    CSV 옆 메타데이터에 남긴다. 여기 없는 알고리즘은 공용 기본값(DEFAULT_CONFIG,
    waypoint_refinement.py의 _ALNS_*·_MAX_SHAKE_LEVEL·_MAX_ITERATIONS)으로 돈다."""
    return {
        algo: {
            name: asdict(value) if name == "config" else dict(value)
            for name, value in _ALGORITHM_DEFAULTS[algo].items()
        }
        for algo in algos if algo in _ALGORITHM_DEFAULTS
    }

TIMEOUT_SEC = 600.0  # 400 -> 600 (9km grasp-wp-vns 단독 170.8초 실측 + 6워커 경합 여유)
CHECKPOINT_EVERY = 25

_POOL_GRAPH = None
# 주의: 워커가 처리하는 모든 태스크가 이 전역을 재사용한다 — 그래프를 변형하는 engine을
# 추가한다면 자체 G.copy()가 있는지 반드시 확인할 것(규칙은 benchmark.py 모듈 docstring
# "그래프 공유·변형 규칙" 참고).


def _pool_worker_init():
    global _POOL_GRAPH
    _POOL_GRAPH = _load_default_graph()
    precompute_scoring_features(_POOL_GRAPH)


def _pool_worker_task(solver_key: str, start_node, target_km: float, num_waypoints: int, seed) -> dict:
    params = {
        "target_km": target_km,
        "profile": CIRCULAR_BENCHMARK_PROFILE,
        "time_budget_sec": DEFAULT_TIME_BUDGET_SEC,
        "num_waypoints": num_waypoints,
    }
    if seed is not None:
        params["seed"] = seed
    return run_solver_task(SOLVER_REGISTRY[solver_key], _POOL_GRAPH, start_node, start_node, params)


def _seed_plan(stage: str, algos: list[str]) -> list[tuple[str, int | None]]:
    """stage 1: 전 알고리즘 시드 1회(BENCHMARK_SEEDS[0]) — 우연이 아니라 커버리지가 목적.
    stage 2: SEED_SENSITIVE_SOLVERS는 BENCHMARK_SEEDS 전부, 그 외는 1회만
    (run_all_scenarios.py::_scenario_tasks와 동일 규칙 — beam-wp는 시드를 읽지 않는다)."""
    if stage == "1":
        return [(algo, BENCHMARK_SEEDS[0]) for algo in algos]
    tasks: list[tuple[str, int | None]] = []
    for algo in algos:
        if algo in SEED_SENSITIVE_SOLVERS:
            tasks.extend((algo, seed) for seed in BENCHMARK_SEEDS)
        else:
            tasks.append((algo, None))
    return tasks


def _parse_algos(raw: str | None) -> list[str]:
    """--algos 문자열을 ALGOS 순서를 유지한 부분집합으로 바꾼다. 오타를 조용히 넘기면
    "돌렸는데 행이 없다"로 끝나므로 모르는 이름은 즉시 막는다."""
    if raw is None:
        return list(ALGOS)
    requested = [name.strip() for name in raw.split(",") if name.strip()]
    unknown = [name for name in requested if name not in ALGOS]
    if unknown:
        raise SystemExit(
            f"알 수 없는 알고리즘: {', '.join(unknown)}\n사용 가능: {', '.join(ALGOS)}"
        )
    return [algo for algo in ALGOS if algo in requested]


def _check_output_path(out_path: str, force: bool) -> None:
    """이미 있는 CSV를 말없이 덮어쓰지 않는다 — 이 러너의 산출물은 한 번 돌리는 데
    수십 분이 들고, 과거 실행분이 알고리즘 제외 결정 같은 판단의 유일한 근거로 남아 있다."""
    if Path(out_path).exists() and not force:
        raise SystemExit(
            f"출력 파일이 이미 있습니다: {out_path}\n"
            "다른 이름을 --out으로 주거나, 기존 파일을 옮긴 뒤 다시 실행하세요 "
            "(덮어쓸 의도라면 --force)."
        )


def _load_dataset() -> dict:
    with open(DATASET_PATH, encoding="utf-8") as f:
        return json.load(f)


def _resolve_conditions(dataset: dict, graph) -> list[dict]:
    """start_points x target_kms x num_waypoints 곱집합을 노드로 해석해서 편다."""
    utils = PathUtils(graph)
    resolved_starts = [
        {**sp, "node": utils.find_nearest_node(sp["lat"], sp["lon"])}
        for sp in dataset["start_points"]
    ]
    return [
        {
            "start_id": sp["id"], "start_label": sp["label"], "tier": sp["tier"],
            "start_node": sp["node"], "target_km": target_km, "num_waypoints": n,
        }
        for sp, target_km, n in itertools.product(
            resolved_starts, dataset["target_kms"], dataset["num_waypoints"],
        )
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", choices=["1", "2"], required=True,
                         help="1=탐색(시드 1회), 2=본실행(SEED_SENSITIVE_SOLVERS는 시드 10회)")
    parser.add_argument("--algos", default=None,
                         help=f"쉼표로 구분한 알고리즘 부분집합(기본: 전체 {len(ALGOS)}종). "
                              "알고리즘별 기본값이 바뀐 알고리즘만 재실행할 때 쓴다 — 모듈 docstring의 "
                              "'부분 재실행' 참고")
    parser.add_argument("--out", default=None,
                         help="결과 CSV 경로(기본: benchmarks/density_stratified_stage{stage}_results.csv). "
                              "부분 재실행은 전체 실행분과 섞이지 않도록 반드시 따로 지정한다")
    parser.add_argument("--force", action="store_true",
                         help="출력 CSV가 이미 있어도 덮어쓴다(기본은 중단)")
    parser.add_argument("--dry-run", action="store_true",
                         help="실행하지 않고 총 실행 수만 계산해서 출력")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    algos = _parse_algos(args.algos)
    out_path = args.out or f"benchmarks/density_stratified_stage{args.stage}_results.csv"

    dataset = _load_dataset()
    seed_plan = _seed_plan(args.stage, algos)
    n_scenario_combos = (
        len(dataset["start_points"]) * len(dataset["target_kms"]) * len(dataset["num_waypoints"])
    )
    total = n_scenario_combos * len(seed_plan)
    print(
        f"stage={args.stage}: 출발지 {len(dataset['start_points'])} x 거리 {len(dataset['target_kms'])} x "
        f"N {dataset['num_waypoints']} x (algo, seed) 조합 {len(seed_plan)} = 총 {total}회",
        flush=True,
    )
    if algos != ALGOS:
        print(f"[부분 실행] 알고리즘 {len(algos)}/{len(ALGOS)}종: {', '.join(algos)}", flush=True)
    print(f"출력: {out_path}", flush=True)
    if args.dry_run:
        return

    _check_output_path(out_path, args.force)

    graph = _load_default_graph()  # 부모 프로세스: find_nearest_node 해석에만 사용
    conditions = _resolve_conditions(dataset, graph)

    print("워커 풀 준비 중...", flush=True)
    t0 = time.perf_counter()
    pool = multiprocessing.get_context("spawn").Pool(processes=args.workers, initializer=_pool_worker_init)
    print(f"워커 풀 준비 완료: {time.perf_counter() - t0:.1f}초", flush=True)

    t_start = time.perf_counter()
    async_results = [
        (cond, algo, seed, pool.apply_async(
            _pool_worker_task,
            args=(algo, cond["start_node"], cond["target_km"], cond["num_waypoints"], seed),
        ))
        for cond in conditions
        for algo, seed in seed_plan
    ]

    columns = ["start_id", "start_label", "tier", "target_km", "num_waypoints", "seed", *RESULT_COLUMNS]

    rows = []
    for i, (cond, algo, seed, ar) in enumerate(async_results, 1):
        solver = SOLVER_REGISTRY[algo]
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
            pd.DataFrame(rows, columns=columns).to_csv(out_path, index=False)

    pool.close()
    pool.join()

    result_df = pd.DataFrame(rows, columns=columns)
    meta_path = save_run_metadata(
        out_path, runner=f"run_density_stratified_scenarios(stage={args.stage})",
        stage=args.stage, dataset=str(DATASET_PATH),
        start_points=dataset["start_points"], target_kms=dataset["target_kms"],
        num_waypoints=dataset["num_waypoints"], algos=algos,
        algorithm_defaults=algorithm_defaults(algos),
        seeds=BENCHMARK_SEEDS if args.stage == "2" else [BENCHMARK_SEEDS[0]],
        workers=args.workers, timeout_sec=TIMEOUT_SEC, time_budget_sec=DEFAULT_TIME_BUDGET_SEC,
        circular_profile=CIRCULAR_BENCHMARK_PROFILE,
    )

    print(f"\n전체 소요 시간: {time.perf_counter() - t_start:.1f}초")
    print(f"결과 저장 완료: {out_path}")
    print(f"메타데이터 저장 완료: {meta_path}\n")

    print("=== tier x num_waypoints 게이트 통과율 ===")
    summary = result_df.groupby(["tier", "num_waypoints"]).agg(
        시도횟수=("status", "count"),
        성공=("status", lambda s: (s == "ok").sum()),
        게이트통과율=("passed", lambda s: s.mean() if s.notna().any() else None),
        평균초=("elapsed_sec", "mean"),
        최대초=("elapsed_sec", "max"),
    ).round(4)
    print(summary.to_string())
    print(
        "\n[주의] 위 평균은 성공한 행만으로 계산됩니다. 조건별 짝지은 비교와 분산·최악값은 "
        f"python -m benchmarks.aggregate_results {out_path} 로 내세요(조건 키에 start_id·"
        "num_waypoints 포함). 부분 실행 CSV는 재사용분과 합친 뒤 집계해야 합니다."
    )


if __name__ == "__main__":
    import logging
    import sys
    # Windows cp949 콘솔은 docstring의 em dash(—)를 인코딩하지 못해 --help가 죽는다.
    # 인코딩 자체는 그대로 둬야 한글이 콘솔에서 안 깨지므로 에러 처리만 바꾼다.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] [%(name)s] %(message)s")
    main()
