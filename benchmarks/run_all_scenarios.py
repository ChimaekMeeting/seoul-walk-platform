# run_all_scenarios.py

import json
import multiprocessing
import time

import pandas as pd

from benchmarks.config import (
    BENCHMARK_SEEDS,
    CIRCULAR_BENCHMARK_PROFILE,
    DEFAULT_TIME_BUDGET_SEC,
    ROUTE_ENGINE_DATASET,
)
from benchmarks.benchmark import _load_default_graph, SEED_SENSITIVE_SOLVERS, SOLVER_REGISTRY
from benchmarks.results import RESULT_COLUMNS, failed_row, run_solver_task
from benchmarks.run_metadata import save_run_metadata
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.scoring.scoring_engine import precompute_scoring_features

# 편도(최단거리) 계열 9종은 2026-09-11 커밋 4c7c924에서 SOLVER_REGISTRY에서 제외했다.
# 순환 경로 검증이 끝난 뒤 리팩토링에서 되살린다 — 복구는
#   git show 4c7c924 -- benchmarks/benchmark.py
# 빈 목록이면 main()의 `if not algos: continue`가 편도 시나리오를 건너뛴다.
ONEWAY_ALGOS: list[str] = []

# 레거시 순환 4종(beam/grasp/alns/rcsp-circular)도 같은 커밋에서 빠졌다. 이쪽은 되살릴
# 계획이 없다 — 신세대(grasp_waypoint_common 계열 / waypoint_beam+adapter) 9종으로 대체됐다.
CIRCULAR_ALGOS = [
    "grasp-wp-local", "grasp-wp-vnd", "grasp-wp-vns", "grasp-wp-alns",
    # Beam 계열(2026-09-10 추가): SOLVER_REGISTRY에는 등록돼 있었는데 이 격자에만 빠져
    # 있어서 GRASP과 같은 조건에서 비교할 수 없었다.
    "beam-wp", "beam-wp-local", "beam-wp-vnd", "beam-wp-vns", "beam-wp-alns",
]

_POOL_GRAPH = None  # 워커 프로세스 전역 — 워커당 1번만 채워짐(그래프 재전송 없음)
# 주의(2026-08-30): 이 전역은 워커가 처리하는 모든 태스크(여러 시나리오·algo 조합)가
# 그대로 재사용한다 — benchmark.py::_run_single()과 달리 호출마다 pickle로 재격리되지
# 않는다. 그래프를 변형하는 engine을 새로 등록한다면 그 engine이 자체적으로 G.copy()를
# 하는지 반드시 확인할 것(자세한 규칙은 benchmark.py 모듈 docstring "그래프 공유·변형
# 규칙" 참고) — 안 하면 그 변형이 이후 다른 태스크로 새어나가는 버그가 된다.


def _pool_worker_init():
    """워커 프로세스 시작 시 1회만 실행 — 그래프를 이 워커 메모리 안에 준비."""
    global _POOL_GRAPH
    _POOL_GRAPH = _load_default_graph()
    precompute_scoring_features(_POOL_GRAPH)


def _pool_worker_task(solver_key: str, start_node, target_node, params: dict) -> dict:
    """태스크마다 실행. solver 인스턴스·그래프를 매번 안 받고, solver_key로
    SOLVER_REGISTRY에서 찾고 그래프는 워커 전역(_POOL_GRAPH)을 그대로 쓴다.

    결과 행 생성은 benchmarks/results.py::run_solver_task()가 전담한다 — 예전에는 이
    함수가 dict 리터럴을 직접 들고 있어서, 컬럼이 추가될 때마다 여기가 빠졌다
    (num_waypoints_used / effective_waypoints_used / pool_cache_* 4종이 실제로 누락).
    """
    return run_solver_task(SOLVER_REGISTRY[solver_key], _POOL_GRAPH, start_node, target_node, params)


def _scenario_tasks(algos: list[str]) -> list[tuple[str, int | None]]:
    """알고리즘별로 돌릴 (algo, seed) 조합.

    확률적 알고리즘의 분산·최악값을 보려면 조건당 여러 시드가 필요하지만, 시드를 읽지
    않는 solver까지 반복하면 실행 시간만 늘어난다(SEED_SENSITIVE_SOLVERS 참고).
    """
    tasks: list[tuple[str, int | None]] = []
    for key in algos:
        if key in SEED_SENSITIVE_SOLVERS:
            tasks.extend((key, seed) for seed in BENCHMARK_SEEDS)
        else:
            tasks.append((key, None))
    return tasks


def _run_scenario_with_pool(pool, algos, start_node, target_node, base_params, timeout_sec=30.0) -> pd.DataFrame:
    """이미 떠 있는 워커 풀에 (알고리즘 × 시드) 태스크를 제출하고 결과를 모은다.

    타임아웃 시 해당 워커는 죽이지 않고 결과만 실패 처리한다(하드킬 포기 — 절충안).
    죽지 않은 태스크가 계속 돌면 같은 풀의 이후 측정치가 부풀 수 있다는 점에 주의.
    """
    circular = start_node == target_node

    async_results = []
    for key, seed in _scenario_tasks(algos):
        params = dict(base_params)
        if seed is not None:
            params["seed"] = seed
        async_results.append(
            (key, seed, pool.apply_async(_pool_worker_task, args=(key, start_node, target_node, params)))
        )

    rows = []
    for key, seed, ar in async_results:
        solver = SOLVER_REGISTRY[key]
        try:
            row = ar.get(timeout=timeout_sec)
        except multiprocessing.TimeoutError:
            row = failed_row(
                solver, "timeout", timeout_sec,
                f"timeout after {timeout_sec}s (worker 강제종료 안 함 — 절충안)",
                base_params.get("target_km"), circular,
            )
        row["seed"] = seed
        rows.append(row)

    return pd.DataFrame(rows, columns=["seed", *RESULT_COLUMNS])


def main():
    print("워커 풀 준비 중...", flush=True)
    t0 = time.perf_counter()
    pool = multiprocessing.get_context("spawn").Pool(processes=6, initializer=_pool_worker_init)
    print(f"워커 풀 준비 완료: {time.perf_counter() - t0:.1f}초", flush=True)

    graph = _load_default_graph()  # 부모 프로세스에선 노드 탐색(find_nearest_node)에만 사용
    utils = PathUtils(graph)

    with open(ROUTE_ENGINE_DATASET, encoding="utf-8") as f:
        dataset = json.load(f)

    scenarios = dataset["scenarios"]
    print(f"시나리오 {len(scenarios)}개 테스트 (oneway {sum(1 for s in scenarios if s['mode']=='oneway')}개, circular {sum(1 for s in scenarios if s['mode']=='circular')}개)\n", flush=True)

    all_rows = []
    t_start = time.perf_counter()

    for i, case in enumerate(scenarios, 1):
        mode = case["mode"]
        algos = ONEWAY_ALGOS if mode == "oneway" else CIRCULAR_ALGOS
        if not algos:
            continue

        start_node = utils.find_nearest_node(case["start_lat"], case["start_lon"])
        target_node = utils.find_nearest_node(case["end_lat"], case["end_lon"]) if mode == "oneway" else start_node

        # 순환 비교는 프로필을 고정한다. 현재 CIRCULAR_ALGOS 9종은 전부 mode="distance"
        # 고정이라 profile을 아예 읽지 않으므로, 고정은 결과에 영향이 없고 CSV에 "프로필
        # 없이 돌았다"는 사실을 명시하는 역할만 한다(프로필을 읽던 레거시 grasp-circular/
        # beam-circular는 4c7c924에서 제외돼 두 진영 간 목적함수 불일치는 소멸했다).
        # 편도는 프로필을 정상적으로 쓰므로 시나리오 값을 그대로 둔다.
        profile = case["profile"] if mode == "oneway" else CIRCULAR_BENCHMARK_PROFILE
        fixed_note = " (고정)" if profile != case["profile"] else ""
        print(
            f"[{i}/{len(scenarios)}] {case['id']} ({mode}, profile={profile}{fixed_note}, "
            f"target_km={case['target_km']}) 시작...",
            flush=True,
        )

        params = {
            "target_km": case["target_km"],
            "profile": profile,
            "time_budget_sec": DEFAULT_TIME_BUDGET_SEC,
        }
        df = _run_scenario_with_pool(pool, algos, start_node, target_node, params, timeout_sec=30.0)
        df.insert(0, "scenario_id", case["id"])
        df.insert(1, "mode", mode)
        all_rows.append(df)

        ok_count = (df["status"] == "ok").sum()
        passed_count = (df["passed"] == True).sum()  # noqa: E712 — NaN 섞인 컬럼이라 `is True` 불가
        print(f"  -> {ok_count}/{len(df)} ok, 게이트 통과 {passed_count}건", flush=True)

    pool.close()
    pool.join()

    result_df = pd.concat(all_rows, ignore_index=True)
    out_path = "all_scenarios_results.csv"
    result_df.to_csv(out_path, index=False)
    meta_path = save_run_metadata(
        out_path, runner="run_all_scenarios",
        seeds=BENCHMARK_SEEDS, scenarios=len(scenarios),
        oneway_algos=ONEWAY_ALGOS, circular_algos=CIRCULAR_ALGOS,
        circular_profile=CIRCULAR_BENCHMARK_PROFILE,
        time_budget_sec=DEFAULT_TIME_BUDGET_SEC, workers=6, timeout_sec=30.0,
    )

    print(f"\n전체 소요 시간: {time.perf_counter() - t_start:.1f}초")
    print(f"결과 저장 완료: {out_path}")
    print(f"메타데이터 저장 완료: {meta_path}\n")

    print("=== 알고리즘별 요약 ===")
    summary = result_df.groupby("algorithm").agg(
        시도횟수=("status", "count"),
        성공=("status", lambda s: (s == "ok").sum()),
        게이트통과율=("passed", lambda s: s.mean() if s.notna().any() else None),
        평균초=("elapsed_sec", "mean"),
        최대초=("elapsed_sec", "max"),
        평균find_path초=("find_path_sec", "mean"),
        평균거리편차km=("distance_deviation_km", "mean"),
        평균우회도=("overlap_ratio", "mean"),      # 편도 solver만 값이 있다(순환은 None)
        평균재통행=("repeated_edge_ratio", "mean"),  # 구 평균자기중복(edge_overlap_ratio)
        평균원형성=("circularity_q", "mean"),
    ).round(4)

    print(summary.to_string())
    print(
        "\n[주의] 위 평균들은 성공한 행만으로 계산됩니다. 어려운 조건에서 실패하는 알고리즘일수록 "
        "쉬운 케이스만 남아 품질 평균이 좋아 보이므로, 반드시 게이트통과율과 함께 읽으세요. "
        "게이트는 순환 행에만 적용되며(편도는 None), 조건별 짝지은 비교와 분산·최악값은 "
        "별도 집계(이슈 G)에서 냅니다."
    )

    TARGET_AGNOSTIC_ALGOS = {"A*(oneway)", "Dijkstra(oneway)", "Bidirectional A*(oneway)"}
    hit = TARGET_AGNOSTIC_ALGOS & set(summary.index)
    if hit:
        print(
            f"\n[참고] {', '.join(sorted(hit))}는 target_km을 고려하지 않고 순수 최단경로만 구합니다. "
            "위 표의 평균거리편차km은 이 알고리즘들에겐 '목표 거리 달성도'가 아니라 출발-도착 간 "
            "자연 최단거리와 target_km의 우연한 차이일 뿐이므로, 우회 계열 solver와 나란히 비교하지 마세요."
        )


if __name__ == "__main__":
    main()
