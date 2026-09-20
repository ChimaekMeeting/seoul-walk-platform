"""
benchmarks/run_grasp_alns_weighted_check.py

"[TEST] 가중치 반영 후 GRASP+ALNS 검증"(#495) — #476(벤치마크 안전/편안 가중 비용
배선)이 병합된 뒤, 서비스 확정 엔진 grasp-wp-alns가 실제로 --safety/--comfort와
함께 끝까지 도는지, 그리고 가중치가 커질수록 후보 다양성·응답 시간·게이트 통과율이
무너지지 않는지 세 지점(alpha+beta 입력 기준 0 / 0.25+0.15 / 0.45+0.3)에서 확인한다.
#476 자체의 스모크는 grasp-wp-local/beam-wp-local로만 했고 grasp-wp-alns로는
검증한 적이 없었다.

run_benchmark()의 멀티프로세스 격리(_run_single)를 쓰지 않고 solver.solve()를 이
프로세스 안에서 직접 반복 호출한다 — "서로 다른 경로 수"(route_diversity.py)를 재려면
raw_result["paths"]가 필요한데, build_result_row()가 이를 요약 지표로 바꿔버려
멀티프로세스 부모로 넘어오지 않기 때문이다. 대신 timeout에 걸린 시행이 좀비로 남을
위험이 있다(원 benchmark.py는 별도 프로세스+강제종료로 막는다) — N=120×3=360회 실행
기준으로는 타임아웃이 한 번도 없었다(2026-09-20 관측, 아래 참고).

기존 CSV와의 회귀 비교(원 이슈 To-Do "alpha=beta=0 회귀 — 기존 CSV와 완전 일치 확인")는
수행하지 않았다 — 저장소에 남아 있던 grasp-alns 관련 CSV(alns_sweep_results.csv 등)는
전부 #474(그래프 원본을 artifact 하나로 통일) 이전, 즉 별도 parquet fixture(160,328
노드/223,927엣지)로 만든 결과라 지금 쓰는 통일된 artifact(160,197/223,693)와 노드
ID 자체가 달라 완전 일치 비교 대상이 될 수 없었다. 이번 실행의 baseline 120회
결과(RESULTS_DIR/grasp_alns_weighted_check_raw.csv, git 미추적)가 #474 이후 첫
기준선이므로, 다음번 관련 코드 변경 뒤에는 이 CSV와 비교하면 된다.

실행: poetry run python -m benchmarks.run_grasp_alns_weighted_check --n-baseline 120 --n-weighted 120
(poetry 환경 밖 python은 버전이 달라 미세하게 다른 수치가 나올 수 있음)

관측(2026-09-20, 실그래프 artifact v3-2026-09-19, 노드 160197/엣지 223693,
start_node=largest_cc의 최소 id, target_km=3.0, 지점당 120회 순차 실행):

| 지점 | alpha/beta(유효값) | 게이트 통과율 | elapsed_sec(평균/p95/최악) | 거리편차 평균 | 서로 다른 경로 수 |
|---|---|---|---|---|---|
| baseline | 0.0/0.0 | 120/120 | 1.57/2.18/2.74s | 0.020km | 25/120 |
| mid | 0.25/0.15 | 120/120 | 2.03/2.86/3.28s | 0.026km | 24/120 |
| upper | 0.45/0.3 -> 0.42/0.28(비례 축소) | 120/120 | 2.54/3.86/5.98s | 0.028km | 24/120 |

이슈의 "되돌아갈 기준" 대조 — 전부 조정 불필요:
- 서로 다른 경로 수 5개 미만: 세 지점 모두 24~25개로 여유 있게 통과.
- 동시 3건 최악값 40초 초과: 개별 worst가 2.7~6.0초. 다만 이 실행은 순차 단일
  프로세스라 "동시 3건"이 뜻하는 동시성 부하 자체를 잰 게 아니라는 점은 남는다.
- 게이트 통과율이 61/72 대비 하락: 세 지점 다 100%라 하락 없음.
upper 지점에서 safety+comfort=0.75가 WALK_WEIGHT_LIMIT(0.7)을 넘어 0.42/0.28로
비례 축소되는 것도 실측으로 확인됐다(normalize_preference_weights 설계대로).
"""
import argparse
import time

import pandas as pd

from benchmarks.benchmark import SOLVER_REGISTRY, _build_cost_context, _load_default_graph
from benchmarks.config import RESULTS_DIR
from benchmarks.results import build_result_row, validate_solver_result
from benchmarks.route_diversity import distinct_route_report
from src.route_engine.scoring.scoring_engine import precompute_scoring_features

# 이슈 원문의 세 지점. safety/comfort는 --safety/--comfort 입력값이지 정규화 후
# alpha/beta가 아니다(docs/route_engine/README.md "선호도와 alpha/beta는 다릅니다" 참고)
# — 실제 alpha/beta는 cost_context에서 읽어 CSV에 함께 남긴다.
POINTS = [
    ("baseline", 0.0, 0.0),
    ("mid", 0.25, 0.15),
    ("upper", 0.45, 0.3),
]

# 회귀 비교 대상 CSV. 위 docstring 참고 — #474 이전 CSV는 그래프가 달라 못 쓰므로
# 지금은 비워 둔다. 이 스크립트를 다시 돌려 회귀를 확인하려면, RESULTS_DIR에 보존해 둔
# 이전 baseline raw CSV 경로를 넣고 _check_regression()을 채운다.
REGRESSION_BASELINE_CSV = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GRASP+ALNS 가중치 3점 검증")
    parser.add_argument("--n-baseline", type=int, default=120, help="baseline(alpha=beta=0) 반복 횟수")
    parser.add_argument("--n-weighted", type=int, default=120, help="mid/upper 각각의 반복 횟수")
    parser.add_argument("--target-km", type=float, default=3.0)
    parser.add_argument("--timeout", type=float, default=30.0, help="1회 solve() 최대 허용 시간(초). "
                         "초과해도 강제 종료하지 않고 경고만 남긴다(위 docstring 참고).")
    return parser.parse_args()


def _run_point(solver, graph, start_node, target_node, label, safety, comfort, n_runs, target_km, timeout):
    cost_context = _build_cost_context(graph, safety, comfort)
    alpha = cost_context.alpha if cost_context is not None else 0.0
    beta = cost_context.beta if cost_context is not None else 0.0

    rows = []
    paths = []
    for seed in range(n_runs):
        params = {"target_km": target_km, "seed": seed, "cost_context": cost_context}
        t0 = time.perf_counter()
        try:
            raw = solver.solve(graph, start_node, target_node, params)
            elapsed = time.perf_counter() - t0
            if elapsed > timeout:
                print(f"  [경고] [{label}] seed={seed} elapsed={elapsed:.1f}s > timeout={timeout}s "
                      f"(강제 종료 안 함 - 결과는 그대로 기록)")
            result = validate_solver_result(raw)
            row = build_result_row(solver, graph, params, elapsed, result, circular=True)
        except Exception as e:  # noqa: BLE001
            elapsed = time.perf_counter() - t0
            row = {"algorithm": solver.name, "status": "failed", "elapsed_sec": elapsed, "error": repr(e)}
            paths.append(None)
        else:
            paths.append(raw["paths"][0])
        row["point"] = label
        row["safety_input"] = safety
        row["comfort_input"] = comfort
        row["alpha_effective"] = alpha
        row["beta_effective"] = beta
        row["seed"] = seed
        rows.append(row)

    valid_paths = [p for p in paths if p is not None]
    diversity = distinct_route_report(valid_paths)
    return pd.DataFrame(rows), diversity


def _check_regression() -> None:
    if REGRESSION_BASELINE_CSV is None:
        print("\n[회귀 비교 건너뜀] REGRESSION_BASELINE_CSV가 지정되지 않았습니다 - "
              "위 docstring 참고(#474 이전 CSV는 그래프가 달라 비교 불가).")
        return
    # TODO: 기존 CSV를 읽어 동일 조건(start_node/target_km/seed)의 행과
    # distance_km/cost/repeated_edge_ratio 등을 비교해 완전 일치 여부를 보고한다.
    raise NotImplementedError


def main() -> None:
    args = parse_args()
    graph = _load_default_graph()
    if graph is None:
        raise SystemExit("그래프 artifact를 못 찾았습니다.")

    import networkx as nx
    largest_cc = max(nx.connected_components(graph), key=len)
    start_node = sorted(largest_cc)[0]
    target_node = start_node

    print("스코어링 feature 캐시 전처리 중...")
    precompute_scoring_features(graph)

    solver = SOLVER_REGISTRY["grasp-wp-alns"]

    all_dfs = []
    summaries = []
    for label, safety, comfort in POINTS:
        n_runs = args.n_baseline if label == "baseline" else args.n_weighted
        print(f"\n=== {label}: safety={safety}, comfort={comfort}, n_runs={n_runs} ===")
        df, diversity = _run_point(
            solver, graph, start_node, target_node, label, safety, comfort,
            n_runs, args.target_km, args.timeout,
        )
        all_dfs.append(df)

        n_ok = (df["status"] == "ok").sum() if "status" in df else 0
        n_passed = df["passed"].sum() if "passed" in df else None
        summary = {
            "point": label, "safety_input": safety, "comfort_input": comfort,
            "n_runs": n_runs, "n_ok": n_ok, "n_passed": n_passed,
            "gate_pass_rate": (n_passed / n_runs) if n_passed is not None else None,
            "elapsed_sec_mean": df["elapsed_sec"].mean() if "elapsed_sec" in df else None,
            "elapsed_sec_p95": df["elapsed_sec"].quantile(0.95) if "elapsed_sec" in df else None,
            "elapsed_sec_worst": df["elapsed_sec"].max() if "elapsed_sec" in df else None,
            "distance_deviation_km_mean": df["distance_deviation_km"].mean() if "distance_deviation_km" in df else None,
            "repeated_edge_ratio_mean": df["repeated_edge_ratio"].mean() if "repeated_edge_ratio" in df else None,
            **diversity,
        }
        summaries.append(summary)
        print(f"  n_ok={n_ok}/{n_runs}, gate_pass_rate={summary['gate_pass_rate']}, "
              f"n_distinct_routes={diversity['n_distinct_routes']}")

    raw_path = RESULTS_DIR / "grasp_alns_weighted_check_raw.csv"
    summary_path = RESULTS_DIR / "grasp_alns_weighted_check_summary.csv"
    pd.concat(all_dfs, ignore_index=True).to_csv(raw_path, index=False)
    pd.DataFrame(summaries).to_csv(summary_path, index=False)
    print(f"\nraw 저장: {raw_path}\nsummary 저장: {summary_path}")

    _check_regression()


if __name__ == "__main__":
    main()
