"""
benchmarks/run_grasp_alns_weighted_check_density.py

run_grasp_alns_weighted_check.py(#495)는 출발지 하나(node=1, 최대 연결요소의 최소
id)에서만 grasp-wp-alns + 가중 비용을 확인했다 — 이 결과만으로 "조정 불필요"를 모든
지역에 일반화할 근거는 없었다. 이 저장소에는 이미 그 정확한 선례가 있다:
grasp_alns_candidate_limit_check(#432 계열)에서 7km·N=4 단일 조건은 "채택 0/60"으로
나왔지만 전 조건 스윕에서는 11.8%로 결론이 뒤집혔다(docs/route_engine/README.md
"GRASP+ALNS candidate_limit" 절 참고). 밀도(경유지 후보 풀 크기)가 다르면 가중
비용의 영향도 달라질 수 있다는 뜻이라, node=1 하나로 낸 결론을 밀도 티어별로
보완 확인한다.

`benchmarks/datasets/circular_density_stratified.json`의 4개 밀도 티어(dense/medium/
sparse/rural) 중 시간 제약으로 3개(dense/sparse/rural, 각 티어 대표 지점 1곳)만 골라
가장 스트레스가 큰 지점(#495의 "upper", safety=0.45/comfort=0.3)에서만 지점당 120회
돈다 — #495처럼 세 지점(baseline/mid/upper) 전체를 매 티어마다 반복하지 않는다.

측정 방식은 run_grasp_alns_weighted_check.py와 같다: run_benchmark()의 멀티프로세스
격리 대신 solver.solve()를 직접 반복 호출한다(경로 다양성 계산에 raw paths가 필요).

실행: poetry run python -m benchmarks.run_grasp_alns_weighted_check_density

관측(2026-09-20, 실그래프 artifact v3-2026-09-19, 노드 160197/엣지 223693,
target_km=3.0, safety=0.45/comfort=0.3, 티어당 120회):

| 티어 | 대표 지점 | 노드 | 게이트 통과율 | elapsed_sec(평균/최악) | 서로 다른 경로 수 |
|---|---|---:|---:|---:|---:|
| dense | 목동 아파트 | 125636 | 120/120 (100%) | 3.07/8.99s | 27/120 |
| sparse | 잠실 아파트 | 196450 | 119/120 (99.2%) | 1.91/4.23s | 36/120 |
| rural | 은평 뉴타운 | 107890 | 93/120 (77.5%) | 1.28/2.57s | 32/120 |

추가로 rural만 baseline(safety=0/comfort=0, 가중치 없음, 같은 node=107890/
target_km=3.0/seed 0~119)도 확인했다: 97/120(80.8%), 실패 23건 전부 `spike_count`.
이 스크립트 자체는 upper 지점만 도니 재현하려면 `_build_cost_context(graph, 0.0, 0.0)`
으로 바꿔서 rural 노드만 따로 돌려야 한다.

**이 입력·이 머신에서의 관측이며 고정 기대값이 아니다.**

- **rural 티어의 낮은 게이트 통과율은 가중치 때문이 아니다.** baseline 80.8% vs
  upper 77.5% — 차이(3.3%p)가 seed 노이즈 범위 안이라, 가중 비용을 켜고 끄고와
  무관하게 rural 지역은 원래도 통과율이 낮다. "가중치가 유도한 우회가 급회전을
  만든다"는 최초 가설은 이 baseline 대조로 기각됐다.
- **즉 이건 #495(가중치 검증)의 범위 밖이다.** rural(저밀도) 지역에서 `spike_count`
  게이트 통과율이 기준값(61/72≈84.7%)보다 낮은 것은 가중 비용 배선과 무관하게
  이전부터 있던 현상이며, `grasp-wp-alns`의 구축·정제 단계가 성긴 도로망에서
  급회전을 얼마나 잘 피하는지에 관한 별도 문제다. dense/sparse는 baseline 대조를
  하지 않았다 — upper에서 이미 99~100%로 충분히 높아 대조해도 결론이 바뀔
  가능성이 낮다고 보고 시간을 아꼈다.
- 서로 다른 경로 수(5개 미만이면 조정)와 응답 시간(동시 3건 40초 초과)은 세 티어
  모두 여유 있게 통과한다 — 가중치 관련 기준에는 걸리는 게 없다.
- **원인 규명(구축 단계가 급회전을 만드는지, ALNS repair가 급회전을 못 없애는지)과
  대응 여부는 이 러너의 범위 밖이다.** 저밀도 지역 `spike_count` 통과율 문제는
  별도 이슈로 분리해서 다뤄야 한다.
"""
import time

import pandas as pd

from benchmarks.benchmark import SOLVER_REGISTRY, _build_cost_context, _load_default_graph
from benchmarks.config import RESULTS_DIR
from benchmarks.results import attach_cost_context_diagnostics, build_result_row, validate_solver_result
from benchmarks.route_diversity import distinct_route_report
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.scoring.scoring_engine import precompute_scoring_features

# benchmarks/datasets/circular_density_stratified.json의 4개 티어 중 시간 제약으로
# 3개만: 극단(dense/rural)과 중간 대조군 하나(sparse)로 스트레스가 가장 큰 지점만 본다.
TIERS = [
    ("dense", "목동 아파트", 37.526000, 126.865000),
    ("sparse", "잠실 아파트", 37.512500, 127.083000),
    ("rural", "은평 뉴타운", 37.634000, 126.928000),
]
N_RUNS = 120
TARGET_KM = 3.0
SAFETY, COMFORT = 0.45, 0.3  # #495의 "upper" 지점 — 가장 스트레스가 큰 조건 하나만 본다.


def main() -> None:
    graph = _load_default_graph()
    if graph is None:
        raise SystemExit("그래프 artifact를 못 찾았습니다.")
    utils = PathUtils(graph)

    print("스코어링 feature 캐시 전처리 중...")
    precompute_scoring_features(graph)

    solver = SOLVER_REGISTRY["grasp-wp-alns"]
    cost_context = _build_cost_context(graph, SAFETY, COMFORT)

    all_rows = []
    summaries = []
    for tier, label, lat, lon in TIERS:
        node = utils.find_nearest_node(lat, lon)
        print(f"\n=== {tier}({label}) node={node} ===")
        rows, paths = [], []
        for seed in range(N_RUNS):
            params = {"target_km": TARGET_KM, "seed": seed, "cost_context": cost_context}
            substitutions_before = cost_context.median_substitutions if cost_context is not None else 0
            t0 = time.perf_counter()
            try:
                raw = solver.solve(graph, node, node, params)
                raw = attach_cost_context_diagnostics(raw, cost_context, substitutions_before)
                elapsed = time.perf_counter() - t0
                result = validate_solver_result(raw)
                row = build_result_row(solver, graph, params, elapsed, result, circular=True)
                paths.append(raw["paths"][0])
            except Exception as e:  # noqa: BLE001
                elapsed = time.perf_counter() - t0
                row = {"algorithm": solver.name, "status": "failed", "elapsed_sec": elapsed, "error": repr(e)}
            row.update(tier=tier, start_label=label, start_node=node, seed=seed)
            rows.append(row)
        df = pd.DataFrame(rows)
        all_rows.append(df)

        n_passed = df["passed"].sum() if "passed" in df else None
        diversity = distinct_route_report(paths)
        summary = {
            "tier": tier, "start_node": node, "n_runs": N_RUNS,
            "n_passed": n_passed, "gate_pass_rate": (n_passed / N_RUNS) if n_passed is not None else None,
            "elapsed_sec_mean": df["elapsed_sec"].mean(),
            "elapsed_sec_worst": df["elapsed_sec"].max(),
            **diversity,
        }
        summaries.append(summary)
        print(f"  n_passed={n_passed}/{N_RUNS}, gate_pass_rate={summary['gate_pass_rate']}, "
              f"elapsed_mean={summary['elapsed_sec_mean']:.2f}s, elapsed_worst={summary['elapsed_sec_worst']:.2f}s, "
              f"n_distinct_routes={diversity['n_distinct_routes']}")

    raw_path = RESULTS_DIR / "grasp_alns_weighted_check_density_raw.csv"
    summary_path = RESULTS_DIR / "grasp_alns_weighted_check_density_summary.csv"
    pd.concat(all_rows, ignore_index=True).to_csv(raw_path, index=False)
    pd.DataFrame(summaries).to_csv(summary_path, index=False)
    print(f"\nraw 저장: {raw_path}\nsummary 저장: {summary_path}")


if __name__ == "__main__":
    main()
