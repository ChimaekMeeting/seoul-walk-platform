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
| rural | 은평 뉴타운 | 107890 | **93/120 (77.5%)** | 1.28/2.57s | 32/120 |

**이 입력·이 머신에서의 관측이며 고정 기대값이 아니다.**

- **#495의 "조정 불필요" 결론은 node=1(조밀 지역)에 한정된다 — 저밀도(rural) 지역에는
  적용되지 않는다.** rural 티어 게이트 통과율 77.5%는 이슈가 정한 기준값(61/72≈84.7%)
  보다 낮아, #495 이슈의 "되돌아갈 기준"(게이트 통과율 유의한 하락) 조건에 실제로
  걸린다.
- **실패는 거의 전부 `spike_count`(급회전) 게이트다**(27건 중 26건 단독, 1건은
  `repeated_edge_ratio`와 복합). 거리편차 자체는 크지 않다(2.71~2.92km, target
  3.0km) — 즉 "목표 거리를 못 맞춰서"가 아니라 "가중치가 유도한 우회가 급회전을
  만들어서" 실패한다. 도로망이 성긴 지역일수록 대안 경로가 적어, 가중치가 특정
  방향을 선호하게 만들면 남은 경로에서 급회전이 생기기 쉬운 것으로 보인다.
- 서로 다른 경로 수(5개 미만이면 조정)와 응답 시간(동시 3건 40초 초과)은 세 티어
  모두 여유 있게 통과한다 — 이번에 걸린 기준은 게이트 통과율 하나뿐이다.
- **원인 규명(구축 단계가 급회전을 만드는지, ALNS repair가 급회전을 못 없애는지)과
  대응(예: 저밀도 지역 한정 completion 로직 보정)은 이 러너의 범위 밖이다.** 여기서는
  "저밀도 지역에서 게이트 통과율이 실제로 떨어진다"는 사실 확인까지만 하고, 조치
  여부는 별도 판단이 필요하다.
"""
import time

import pandas as pd

from benchmarks.benchmark import SOLVER_REGISTRY, _build_cost_context, _load_default_graph
from benchmarks.config import RESULTS_DIR
from benchmarks.results import build_result_row, validate_solver_result
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
            t0 = time.perf_counter()
            try:
                raw = solver.solve(graph, node, node, params)
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
