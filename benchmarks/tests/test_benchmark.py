"""
benchmarks/tests/test_benchmark.py

공통 벤치마크 하네스(benchmarks/benchmark.py)의 동작을 검증한다.

이 하네스의 실제 목적은 "적당한 시간 내에(사용자가 불편함을 느끼지 않을 정도) 사용자가
입력한 산책하고 싶은 길이 나오는가"를 확인하는 것이다. 그래서 구성은 아래처럼 나눈다:

  H. 하네스가 안 죽는지 검증하는 "필수" 최소 안전장치만 압축해서 유지
     (인터페이스 규격 / 예외·타임아웃 처리 / 데이터 Export / 그래프 격리 / CLI)
  P. 측정 자체를 신뢰할 수 있는지(반복 안정성, 실제 연산량 반영) — 최소한만 유지
  R. 이 하네스의 핵심 관심사 — 순환 경로 "품질" + "체감 시간":
       - 목표거리 대비 실제거리 편차
       - 루프가 실제로 닫히는지(폐합)
       - 잔가시(갔다가 바로 되돌아오는 구간)
       - 왕복 시 같은 길을 그대로 공유하는지(엣지 재사용)
       - 사용자 체감 시간 예산(time_budget_sec) 이내에 끝나는지
     모두 solver의 자기 신고를 믿지 않고 하네스가 paths/graph에서 독립적으로 계산한다.
"""

import statistics
import threading

import networkx as nx
import pandas as pd
import pytest

from benchmarks import benchmark as bm
from benchmarks.solvers.base_solver import BasePathSolver
from benchmarks.tests.fixtures import (
    BadCostTypeSolver,
    BadPathsTypeSolver,
    CpuLoopSolver,
    FixedPathSolver,
    HangingSolver,
    MissingCostSolver,
    MissingPathsSolver,
    MutatingSolver,
    NonDictReturnSolver,
    NoOverlapRatioSolver,
    ParamDrivenPathSolver,
    RaisingSolver,
    SleepSolver,
)

TEST_TIMEOUT_SEC = 3.0  # 정상/실패 케이스용 넉넉한 하드 타임아웃
# 타임아웃 자체를 검증할 때 쓰는 짧은 타임아웃.
# 주의: process.join(timeout=...)은 spawn 오버헤드까지 포함해서 잰다. 단독 실행 시
# spawn은 ~0.05s지만, 테스트 스위트 안에서 프로세스 spawn이 연달아 누적되면 부하로
# 인해 값이 튈 수 있어(관찰상 순간적으로 0.3s 초과) 넉넉하게 잡는다.
SHORT_TIMEOUT_SEC = 1.5


# ══════════════════════════════════════════════════════════════════════════
# H. 하네스 필수 안전장치 (압축)
# ══════════════════════════════════════════════════════════════════════════

def test_h1_valid_result_ok_and_overlap_ratio_defaults_when_omitted():
    normal = SleepSolver("Normal", sleep_sec=0.0, cost=10.0, overlap_ratio=0.3)
    no_overlap = NoOverlapRatioSolver("NoOverlap")

    df = bm.run_benchmark([normal, no_overlap], None, "A", "B", {}, timeout_sec=TEST_TIMEOUT_SEC)
    by_name = df.set_index("algorithm")

    assert by_name.loc["Normal", "status"] == "ok"
    assert by_name.loc["Normal", "cost"] == 10.0
    assert by_name.loc["Normal", "overlap_ratio"] == 0.3
    assert by_name.loc["NoOverlap", "overlap_ratio"] == 0.0  # 명세상 기본값


@pytest.mark.parametrize(
    "solver_cls",
    [MissingCostSolver, MissingPathsSolver, BadPathsTypeSolver, BadCostTypeSolver, NonDictReturnSolver],
)
def test_h2_invalid_return_shapes_fail_safely(solver_cls):
    df = bm.run_benchmark([solver_cls("Invalid")], None, "A", "B", {}, timeout_sec=TEST_TIMEOUT_SEC)

    assert df.iloc[0]["status"] == "failed"
    assert df.iloc[0]["error"] != ""


def test_h3_missing_solve_implementation_cannot_instantiate():
    class IncompleteSolver(BasePathSolver):
        pass

    with pytest.raises(TypeError):
        IncompleteSolver("Incomplete")


def test_h4_mixed_failures_do_not_stop_pipeline():
    solvers = [
        SleepSolver("Ok", sleep_sec=0.0),
        RaisingSolver("Raise"),
        MissingCostSolver("Missing"),
        HangingSolver("Hang"),
    ]
    df = bm.run_benchmark(solvers, None, "A", "B", {}, timeout_sec=SHORT_TIMEOUT_SEC)
    by_name = df.set_index("algorithm")

    assert len(df) == len(solvers)
    assert by_name.loc["Ok", "status"] == "ok"
    assert by_name.loc["Raise", "status"] == "failed"
    assert by_name.loc["Missing", "status"] == "failed"
    assert by_name.loc["Hang", "status"] == "timeout"


def test_h5_unpicklable_input_fails_without_crashing():
    solver = SleepSolver("Normal", sleep_sec=0.0)
    unpicklable_params = {"lock": threading.Lock()}  # threading.Lock은 pickle 불가

    df = bm.run_benchmark([solver], None, "A", "B", unpicklable_params, timeout_sec=TEST_TIMEOUT_SEC)

    row = df.iloc[0]
    assert row["status"] == "failed"
    assert "spawn" in row["error"].lower() or "pickle" in row["error"].lower()


def test_h6_csv_export_survives_mixed_results_and_roundtrips(tmp_path):
    solvers = [SleepSolver("Ok", sleep_sec=0.0), RaisingSolver("Raise"), HangingSolver("Hang")]
    df = bm.run_benchmark(solvers, None, "A", "B", {}, timeout_sec=SHORT_TIMEOUT_SEC)

    out_path = tmp_path / "benchmark_results.csv"
    df.to_csv(out_path, index=False)  # 실패/타임아웃이 섞여도 예외 없이 끝나야 함
    assert out_path.exists()

    reloaded = pd.read_csv(out_path)
    by_name = reloaded.set_index("algorithm")
    assert list(reloaded.columns) == bm.RESULT_COLUMNS
    assert by_name.loc["Ok", "status"] == "ok"
    assert by_name.loc["Raise", "status"] == "failed"
    assert pd.isna(by_name.loc["Raise", "cost"])


def test_h7_graph_mutation_does_not_leak_to_original():
    original_graph = {"mutated_by": None}
    solvers = [MutatingSolver("MutatorA"), MutatingSolver("MutatorB")]

    bm.run_benchmark(solvers, original_graph, "A", "B", {}, timeout_sec=TEST_TIMEOUT_SEC)

    assert original_graph == {"mutated_by": None}


def test_h8_cli_resolve_and_unknown_name_validation():
    assert len(bm.resolve_solvers(["all"])) == len(bm.SOLVER_REGISTRY)

    key = next(iter(bm.SOLVER_REGISTRY))
    assert bm.resolve_solvers([key]) == [bm.SOLVER_REGISTRY[key]]

    with pytest.raises(SystemExit):
        bm.parse_args(["--algo", "not-a-real-algorithm"])


# ══════════════════════════════════════════════════════════════════════════
# P. 측정 신뢰성 (최소한만 유지)
# ══════════════════════════════════════════════════════════════════════════

def test_p1_repeated_measurement_of_same_solver_is_stable():
    """비교표에 쓸 숫자가 노이즈에 휘둘리지 않는지 (변동계수 확인)."""
    samples = []
    for _ in range(5):
        df = bm.run_benchmark([SleepSolver("Repeat", sleep_sec=0.1)], None, "A", "B", {}, timeout_sec=TEST_TIMEOUT_SEC)
        samples.append(df.iloc[0]["elapsed_sec"])

    mean = statistics.mean(samples)
    stdev = statistics.pstdev(samples)
    cv_pct = (stdev / mean * 100) if mean > 0 else 0.0

    assert all(abs(s - 0.1) < 0.15 for s in samples)
    assert cv_pct < 60


def test_p2_cpu_bound_elapsed_scales_with_work_size():
    """sleep이 아닌 실제 연산량 기반으로도 작업량이 늘면 측정 시간이 늘어나는지."""
    small = CpuLoopSolver("SmallWork", iterations=2_000_000)
    large = CpuLoopSolver("LargeWork", iterations=8_000_000)

    df = bm.run_benchmark([small, large], None, "A", "B", {}, timeout_sec=TEST_TIMEOUT_SEC)
    by_name = df.set_index("algorithm")

    assert by_name.loc["LargeWork", "elapsed_sec"] > by_name.loc["SmallWork", "elapsed_sec"] * 1.5


# ══════════════════════════════════════════════════════════════════════════
# R. 순환 경로 품질 + 체감 시간 — 이 하네스의 존재 목적
# ══════════════════════════════════════════════════════════════════════════

def _build_graph_with_lengths() -> nx.Graph:
    graph = nx.Graph()
    graph.add_edge("A", "B", length=1000)
    graph.add_edge("B", "C", length=1500)
    graph.add_edge("C", "A", length=500)  # A-B-C-A 한 바퀴 = 3000m = 3.0km
    return graph


def test_r1_distance_km_computed_independently_from_graph_edges():
    graph = _build_graph_with_lengths()
    solver = FixedPathSolver("Fixed", path=["A", "B", "C"])  # 1000 + 1500 = 2500m

    df = bm.run_benchmark([solver], graph, "A", "C", {}, timeout_sec=TEST_TIMEOUT_SEC)

    assert df.iloc[0]["distance_km"] == pytest.approx(2.5)


@pytest.mark.parametrize("target_km, expected_deviation", [(3.0, 0.0), (2.5, 0.5)])
def test_r2_distance_deviation_reflects_gap_from_target_km(target_km, expected_deviation):
    graph = _build_graph_with_lengths()
    solver = FixedPathSolver("Loop", path=["A", "B", "C", "A"])  # 3.0km 루프

    df = bm.run_benchmark([solver], graph, "A", "A", {"target_km": target_km}, timeout_sec=TEST_TIMEOUT_SEC)
    row = df.iloc[0]

    assert row["distance_km"] == pytest.approx(3.0)
    assert row["distance_deviation_km"] == pytest.approx(expected_deviation)


@pytest.mark.parametrize("path, expected", [(["A", "B", "C", "A"], True), (["A", "B", "C"], False)])
def test_r3_is_closed_loop_detects_loop_vs_open_path(path, expected):
    solver = FixedPathSolver("Path", path=path)

    df = bm.run_benchmark([solver], None, "A", "C", {}, timeout_sec=TEST_TIMEOUT_SEC)

    assert df.iloc[0]["is_closed_loop"] == expected


def test_r4_distance_metrics_gracefully_none_without_graph_or_target():
    graph = _build_graph_with_lengths()
    solver = FixedPathSolver("Path", path=["A", "B", "C"])

    neither = bm.run_benchmark([solver], None, "A", "C", {}, timeout_sec=TEST_TIMEOUT_SEC).iloc[0]
    assert pd.isna(neither["distance_km"])
    assert pd.isna(neither["target_km"])

    graph_only = bm.run_benchmark([solver], graph, "A", "C", {}, timeout_sec=TEST_TIMEOUT_SEC).iloc[0]
    assert graph_only["distance_km"] == pytest.approx(2.5)
    assert pd.isna(graph_only["target_km"])
    assert pd.isna(graph_only["distance_deviation_km"])

    target_only = bm.run_benchmark(
        [solver], None, "A", "C", {"target_km": 3.0}, timeout_sec=TEST_TIMEOUT_SEC,
    ).iloc[0]
    assert target_only["target_km"] == 3.0
    assert pd.isna(target_only["distance_km"])
    assert pd.isna(target_only["distance_deviation_km"])


def test_r5_distance_computation_failure_does_not_fail_solver_row():
    graph = nx.Graph()
    graph.add_edge("A", "B")  # length 속성 없음
    graph.add_edge("B", "C")
    solver = FixedPathSolver("Path", path=["A", "B", "C"])

    df = bm.run_benchmark([solver], graph, "A", "C", {}, timeout_sec=TEST_TIMEOUT_SEC)
    row = df.iloc[0]

    assert row["status"] == "ok"
    assert pd.isna(row["distance_km"])


def test_r6_target_km_still_reported_on_failed_rows():
    df = bm.run_benchmark([RaisingSolver("Raise")], None, "A", "B", {"target_km": 5.0}, timeout_sec=TEST_TIMEOUT_SEC)
    row = df.iloc[0]

    assert row["status"] == "failed"
    assert row["target_km"] == 5.0


def test_r7_distance_deviation_across_repeated_scenarios_can_be_summarized_with_std():
    """같은 목표(target_km)에 대해 알고리즘이 매번 얼마나 들쭉날쭉하게 목표를 빗나가는지
    통계로 요약할 수 있는지 확인 — '목표거리 대비 편차의 표준편차' 지표의 기반."""
    graph = nx.Graph()
    graph.add_edge("A", "B1", length=1000); graph.add_edge("B1", "C1", length=1000); graph.add_edge("C1", "A", length=800)   # 2.8km
    graph.add_edge("A", "B2", length=1000); graph.add_edge("B2", "C2", length=1000); graph.add_edge("C2", "A", length=1000)  # 3.0km
    graph.add_edge("A", "B3", length=1200); graph.add_edge("B3", "C3", length=1000); graph.add_edge("C3", "A", length=1000)  # 3.2km

    loop_variants = [["A", "B1", "C1", "A"], ["A", "B2", "C2", "A"], ["A", "B3", "C3", "A"]]
    solver = ParamDrivenPathSolver("Loop")

    deviations = []
    for path in loop_variants * 2:  # 6회, 결정론적 순서(무작위 아님 — flaky 방지)
        df = bm.run_benchmark(
            [solver], graph, "A", "A", {"target_km": 3.0, "path": path}, timeout_sec=TEST_TIMEOUT_SEC,
        )
        deviations.append(df.iloc[0]["distance_deviation_km"])

    assert all(d is not None and d >= 0 for d in deviations)
    assert max(deviations) == pytest.approx(0.2, abs=1e-6)
    assert statistics.pstdev(deviations) > 0  # 편차가 실제로 들쭉날쭉함을 통계로 확인


@pytest.mark.parametrize(
    "path, expected_spikes",
    [
        (["A", "B", "C", "D"], 0),            # 깔끔한 경로, 잔가시 없음
        (["A", "B", "A", "C", "D"], 1),        # B로 갔다가 바로 되돌아옴
        (["A", "B", "A", "C", "A", "D"], 2),   # 잔가시 2개
    ],
)
def test_r8_spike_count_detects_dead_end_backtrack(path, expected_spikes):
    solver = FixedPathSolver("Path", path=path)

    df = bm.run_benchmark([solver], None, "A", "D", {}, timeout_sec=TEST_TIMEOUT_SEC)

    assert df.iloc[0]["spike_count"] == expected_spikes


def test_r9_edge_overlap_ratio_detects_shared_outbound_inbound_path():
    clean_loop = FixedPathSolver("Clean", path=["A", "B", "C", "D", "A"])          # 4개 구간 모두 1회씩만 사용
    out_and_back = FixedPathSolver("OutAndBack", path=["A", "B", "C", "B", "A"])   # A-B, B-C 구간을 그대로 왕복

    df = bm.run_benchmark([clean_loop, out_and_back], None, "A", "A", {}, timeout_sec=TEST_TIMEOUT_SEC)
    by_name = df.set_index("algorithm")

    assert by_name.loc["Clean", "edge_overlap_ratio"] == 0.0
    assert by_name.loc["OutAndBack", "edge_overlap_ratio"] == 1.0


def test_r10_within_time_budget_flags_technically_ok_but_too_slow_runs():
    """timeout_sec(하드 킬)엔 안 걸려도, time_budget_sec(UX 체감 기준)은 넘을 수 있음을 구분."""
    fast = SleepSolver("Fast", sleep_sec=0.05)
    slow_but_ok = SleepSolver("SlowButOk", sleep_sec=0.5)

    df = bm.run_benchmark(
        [fast, slow_but_ok], None, "A", "B", {"time_budget_sec": 0.2}, timeout_sec=TEST_TIMEOUT_SEC,
    )
    by_name = df.set_index("algorithm")

    assert by_name.loc["Fast", "status"] == "ok"
    assert bool(by_name.loc["Fast", "within_time_budget"]) is True

    assert by_name.loc["SlowButOk", "status"] == "ok"  # 하드 타임아웃엔 안 걸림
    assert bool(by_name.loc["SlowButOk", "within_time_budget"]) is False  # 그러나 UX 예산은 초과


def test_r11_end_to_end_acceptable_circular_route_within_time_and_distance_and_shape():
    """이 하네스가 존재하는 이유를 그대로 검증하는 통합 시나리오:
    '적당한 시간 내에(time_budget_sec) 사용자가 원하는 거리(target_km)의, 실제로 닫히고
    잔가시/왕복겹침 없는 순환 경로가 나오는가'를 한 번에 확인한다."""
    graph = nx.Graph()
    graph.add_edge("Start", "N1", length=700)
    graph.add_edge("N1", "N2", length=800)
    graph.add_edge("N2", "N3", length=750)
    graph.add_edge("N3", "Start", length=780)  # 총 3030m = 3.03km

    good_loop_path = ["Start", "N1", "N2", "N3", "Start"]
    solver = FixedPathSolver("RealisticAlgo", path=good_loop_path, cost=3.03, sleep_sec=0.1)

    params = {"target_km": 3.0, "time_budget_sec": 3.0}
    df = bm.run_benchmark([solver], graph, "Start", "Start", params, timeout_sec=TEST_TIMEOUT_SEC)
    row = df.iloc[0]

    assert row["status"] == "ok"
    assert bool(row["within_time_budget"]) is True
    assert row["distance_deviation_km"] < 0.3  # 목표 대비 10% 이내
    assert bool(row["is_closed_loop"]) is True
    assert row["spike_count"] == 0
    assert row["edge_overlap_ratio"] == 0.0
