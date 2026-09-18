"""
benchmarks/tests/test_circular_route_scenarios.py

benchmarks/datasets/route_engine.json의 circular 시나리오 25개로 실제 순환 경로
알고리즘(GRASP+VNS / Beam / ALNS)이 만들어내는 경로 자체의 품질을 검증한다.

test_benchmark.py는 DummySolver로 하네스 자체를 검증하지만, 이 파일은 실제 서울
도보 그래프 + 실제 알고리즘으로 "실제로 쓸만한 순환 경로가 나오는가"를 검증한다.
서울 전역 그래프(16만 노드) 로딩 + 알고리즘 75회 이상 실행이 필요해 1~2분 정도
걸린다 — 빠른 단위 테스트가 아니라 통합/특성화(characterization) 테스트다.

임계값은 감으로 잡지 않고 25개 시나리오 전수 실행 실측치에 여유(margin)를 둬서
설정했다. GRASP/ALNS는 seed가 고정(기본 42)돼 있고 Beam은 랜덤성이 아예 없어서,
같은 그래프·시나리오라면 매번 100% 동일한 결과가 나온다 — 즉 이 임계값들은 우연한
변동으로 flaky해질 수 없고, 실제 품질 회귀만 잡아낸다.

실측 결과 (circular 25개 시나리오 1회 전수 실행):
  algorithm   성공률   평균거리편차   평균잔가시  평균왕복겹침
  Beam        25/25   0.178km        0.00        2.9%
  GRASP+VNS   25/25   0.212km        0.04        3.0%
  ALNS        22/25   0.959km        0.50        8.6%   (3건은 경로 생성 자체 실패)

ALNS는 현재 실제로 품질이 떨어진다 — 테스트를 관대하게 잡아 감추지 않고 "지금 이
정도가 기준선"이라고 명시적으로 문서화한다 (더 나빠지면 이 테스트가 잡아낸다).
"""

import json

import networkx as nx
import pandas as pd
import pytest

from benchmarks import benchmark as bm
from benchmarks.config import ROUTE_ENGINE_DATASET
from benchmarks.solvers.alns_solver import AlnsSolver
from benchmarks.solvers.grasp_solver import GraspSolver
from src.route_engine.engines.path_utils import PathUtils

TIMEOUT_SEC = 30.0

# 25개 시나리오 전수 실행 실측치에 여유를 둔 임계값 (결정론적 실행이라 변동 자체가
# 없음 — 실제 품질 회귀만 잡아내는 게 목적).
QUALITY_THRESHOLDS = {
    "Beam":      {"min_success_rate": 1.00, "max_mean_deviation_km": 0.35, "max_mean_spike": 0.2, "max_mean_overlap": 0.10},
    "GRASP+VNS": {"min_success_rate": 1.00, "max_mean_deviation_km": 0.40, "max_mean_spike": 0.3, "max_mean_overlap": 0.10},
    # ALNS는 현재 실제로 12% 실패, 편차도 큼 — 알려진 기준선을 문서화 (더 나빠지면 실패 처리)
    "ALNS":      {"min_success_rate": 0.80, "max_mean_deviation_km": 1.30, "max_mean_spike": 0.8, "max_mean_overlap": 0.15},
}

# 시드 견고성 확인용으로 고정 표본만 사용 (전체 25개 × 여러 시드는 너무 느림)
_SEED_ROBUSTNESS_SCENARIOS = ["circular_01", "circular_10", "circular_20"]
_SEEDS_TO_CHECK = [42, 43, 44]


@pytest.fixture(scope="session")
def real_graph() -> nx.Graph:
    graph = bm._load_default_graph()
    if graph is None:
        pytest.skip("그래프 fixture 없음 — 'python -m benchmarks.build_fixtures'로 먼저 생성하세요")
    return graph


@pytest.fixture(scope="session")
def circular_scenarios() -> list[dict]:
    with open(ROUTE_ENGINE_DATASET, encoding="utf-8") as f:
        dataset = json.load(f)
    return [s for s in dataset["scenarios"] if s["mode"] == "circular"]


@pytest.fixture(scope="session")
def scenario_results(real_graph, circular_scenarios) -> pd.DataFrame:
    """25개 시나리오 × 3개 알고리즘을 세션당 한 번만 실행하고 결과를 공유한다."""
    utils = PathUtils(real_graph)
    solvers = bm.resolve_solvers(["grasp", "beam", "alns"])

    rows = []
    for scenario in circular_scenarios:
        start_node = utils.find_nearest_node(scenario["start_lat"], scenario["start_lon"])
        if start_node is None:
            continue
        params = {"target_km": scenario["target_km"], "profile": scenario["profile"]}
        df = bm.run_benchmark(solvers, real_graph, start_node, start_node, params, timeout_sec=TIMEOUT_SEC)
        df.insert(0, "scenario_id", scenario["id"])
        rows.append(df)

    return pd.concat(rows, ignore_index=True)


# ── 개별 시나리오 불변식 (성공한 실행이라면 항상 성립해야 함) ────────────────────

def test_successful_routes_always_form_a_closed_loop(scenario_results):
    ok_rows = scenario_results[scenario_results["status"] == "ok"]
    assert len(ok_rows) > 0
    assert ok_rows["is_closed_loop"].all(), "status=ok인데 루프가 안 닫힌 경로가 있음"


# ── 알고리즘별 품질 기준선 (25개 시나리오 집계) ──────────────────────────────

@pytest.mark.parametrize("algorithm", ["Beam", "GRASP+VNS", "ALNS"])
def test_algorithm_meets_quality_baseline_across_scenarios(scenario_results, algorithm):
    rows = scenario_results[scenario_results["algorithm"] == algorithm]
    thresholds = QUALITY_THRESHOLDS[algorithm]

    success_rate = (rows["status"] == "ok").mean()
    assert success_rate >= thresholds["min_success_rate"], (
        f"{algorithm} 성공률 {success_rate:.0%} < 기준 {thresholds['min_success_rate']:.0%}"
    )

    ok_rows = rows[rows["status"] == "ok"]
    mean_deviation = ok_rows["distance_deviation_km"].mean()
    assert mean_deviation <= thresholds["max_mean_deviation_km"], (
        f"{algorithm} 평균 거리편차 {mean_deviation:.3f}km > 기준 {thresholds['max_mean_deviation_km']}km"
    )

    mean_spike = ok_rows["spike_count"].mean()
    assert mean_spike <= thresholds["max_mean_spike"], (
        f"{algorithm} 평균 잔가시 {mean_spike:.2f} > 기준 {thresholds['max_mean_spike']}"
    )

    mean_overlap = ok_rows["edge_overlap_ratio"].mean()
    assert mean_overlap <= thresholds["max_mean_overlap"], (
        f"{algorithm} 평균 왕복겹침 {mean_overlap:.1%} > 기준 {thresholds['max_mean_overlap']:.0%}"
    )


# ── 시드 견고성: GRASP/ALNS는 랜덤성을 쓰므로, seed=42 하나로 잘(혹은 나쁘게) 나온
#    게 우연이 아닌지 다른 시드로도 반복 검증한다 (Beam은 랜덤성이 없어 반복 무의미) ──

@pytest.mark.parametrize("solver_cls,algorithm_name", [(GraspSolver, "GRASP+VNS"), (AlnsSolver, "ALNS")])
def test_stochastic_algorithm_is_reasonably_robust_across_seeds(
    real_graph, circular_scenarios, solver_cls, algorithm_name,
):
    """seed 하나(42)의 결과가 우연이 아닌지, 다른 시드로도 확인.

    ALNS는 이미 seed=42에서도 품질이 떨어지는 게 위 테스트에서 확인됐으므로, 여기서는
    '시드를 바꿔도 완전히 붕괴하지 않는지'만 넉넉하게 확인한다 — 이미 알려진 한계를
    다시 실패로 보고하는 게 목적이 아니라, 시드에 따라 더 심각해지는지 감시하는 용도.
    """
    utils = PathUtils(real_graph)
    scenarios_by_id = {s["id"]: s for s in circular_scenarios}

    results = []
    for scenario_id in _SEED_ROBUSTNESS_SCENARIOS:
        scenario = scenarios_by_id[scenario_id]
        start_node = utils.find_nearest_node(scenario["start_lat"], scenario["start_lon"])
        params = {"target_km": scenario["target_km"], "profile": scenario["profile"]}

        for seed in _SEEDS_TO_CHECK:
            solver = solver_cls(name=algorithm_name, seed=seed)
            df = bm.run_benchmark([solver], real_graph, start_node, start_node, params, timeout_sec=TIMEOUT_SEC)
            results.append(df.iloc[0]["status"] == "ok")

    success_rate = sum(results) / len(results)
    assert success_rate >= 0.5, (
        f"{algorithm_name}이 seed 변화에 너무 취약함: {len(results)}회 중 {sum(results)}회만 성공"
    )
