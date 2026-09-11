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

import math
import statistics
import threading

import networkx as nx
import pandas as pd
import pytest

from benchmarks import benchmark as bm
from benchmarks import config as bm_config
from benchmarks import results as bm_results
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
#
# 2026-09-10: 1.5s였을 때 스위트 전체 실행에서 test_h4/test_h6이 간헐적으로 깨졌다
# (같은 테스트를 단독 실행하면 통과 — 부하로 인한 spawn 지연이 원인). 게이트·스윕
# 테스트가 늘면서 프로세스 spawn 횟수가 더 늘어 3.0s로 올린다. 이 값을 올려도
# HangingSolver는 무한 대기라 타임아웃 검증 자체는 그대로 성립한다.
SHORT_TIMEOUT_SEC = 3.0


# ══════════════════════════════════════════════════════════════════════════
# H. 하네스 필수 안전장치 (압축)
# ══════════════════════════════════════════════════════════════════════════

def test_h1_valid_result_ok_and_overlap_ratio_is_none_when_omitted():
    """overlap_ratio를 보고하지 않으면 None으로 남는다(2026-09-10 계약 변경).

    예전 기본값 0.0은, 이 지표를 아예 계산하지 않는 순환 solver의 행을 "겹침 0%"라는
    실측값처럼 보이게 만들었다. 이제 안 준 것과 0.0으로 측정된 것이 구분된다."""
    normal = SleepSolver("Normal", sleep_sec=0.0, cost=10.0, overlap_ratio=0.3)
    no_overlap = NoOverlapRatioSolver("NoOverlap")

    df = bm.run_benchmark([normal, no_overlap], None, "A", "B", {}, timeout_sec=TEST_TIMEOUT_SEC)
    by_name = df.set_index("algorithm")

    assert by_name.loc["Normal", "status"] == "ok"
    assert by_name.loc["Normal", "cost"] == 10.0
    assert by_name.loc["Normal", "overlap_ratio"] == 0.3
    assert pd.isna(by_name.loc["NoOverlap", "overlap_ratio"])


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


def test_r9_repeated_edge_ratio_is_distance_weighted_like_the_engine():
    """재통행 비율은 거리 가중 정의다 — 단순 왕복은 1.0이 아니라 0.5다(2026-09-10 이행).

    엔진은 2026-09-02에 이 정의(waypoint_route_builder.edge_overlap_ratio, 구간의 두 번째
    이후 통행분만 가산)로 옮기고 퇴화 임계값도 0.35로 재조정했는데, 하네스만 이행 전
    정의(통행 횟수 기준, 단순 왕복=1.0)로 남아 있었다. 이제 같은 함수를 쓴다.
    거리 가중이라 graph가 반드시 필요하다.
    """
    graph = nx.Graph()
    for u, v in [("A", "B"), ("B", "C"), ("C", "D"), ("D", "A")]:
        graph.add_edge(u, v, length=1000)

    clean_loop = FixedPathSolver("Clean", path=["A", "B", "C", "D", "A"])          # 4개 구간 모두 1회씩만 사용
    out_and_back = FixedPathSolver("OutAndBack", path=["A", "B", "C", "B", "A"])   # A-B, B-C 구간을 그대로 왕복

    df = bm.run_benchmark([clean_loop, out_and_back], graph, "A", "A", {}, timeout_sec=TEST_TIMEOUT_SEC)
    by_name = df.set_index("algorithm")

    assert by_name.loc["Clean", "repeated_edge_ratio"] == 0.0
    assert by_name.loc["OutAndBack", "repeated_edge_ratio"] == 0.5


def test_r9b_repeated_edge_ratio_needs_graph_and_is_none_without_it():
    """거리 가중 정의라 graph 없이는 계산할 수 없다 — 0.0으로 위장하지 않고 None."""
    solver = FixedPathSolver("NoGraph", path=["A", "B", "A"])

    df = bm.run_benchmark([solver], None, "A", "A", {}, timeout_sec=TEST_TIMEOUT_SEC)

    assert df.iloc[0]["status"] == "ok"
    assert pd.isna(df.iloc[0]["repeated_edge_ratio"])


def _regular_polygon_graph(sides: int, radius_deg: float = 0.01, lat0: float = 37.5, lon0: float = 127.0):
    """중심 (lat0, lon0) 둘레에 정n각형으로 노드를 놓고 이웃끼리 연결한 그래프와 순환 경로.

    circularity_q가 "정n각형이 커질수록 원(1.0)에 가까워진다"는 성질을 갖는지 확인하기 위한
    픽스처. 경도는 cos(lat)만큼 좁아지므로 실제 원이 되도록 보정해서 배치한다.
    """
    graph = nx.Graph()
    cos_lat = math.cos(math.radians(lat0))
    nodes = []
    for i in range(sides):
        theta = 2 * math.pi * i / sides
        lat = lat0 + radius_deg * math.sin(theta)
        lon = lon0 + radius_deg * math.cos(theta) / cos_lat
        graph.add_node(i, lat=lat, lon=lon)
        nodes.append(i)

    for u, v in zip(nodes, nodes[1:] + nodes[:1]):
        length_m = bm_results._EARTH_RADIUS_M * math.radians(
            2 * radius_deg * math.sin(math.pi / sides)
        )
        graph.add_edge(u, v, length=length_m)

    return graph, [*nodes, nodes[0]]


def test_r9c_circularity_q_approaches_one_for_near_circular_loops():
    """등주 지수는 원에 가까울수록 1에 수렴한다 — 변이 많아질수록 값이 커져야 한다."""
    graph_square, path_square = _regular_polygon_graph(4)
    graph_many, path_many = _regular_polygon_graph(64)

    df_square = bm.run_benchmark(
        [FixedPathSolver("Square", path=path_square)], graph_square, 0, 0, {},
        timeout_sec=TEST_TIMEOUT_SEC,
    )
    df_many = bm.run_benchmark(
        [FixedPathSolver("NearCircle", path=path_many)], graph_many, 0, 0, {},
        timeout_sec=TEST_TIMEOUT_SEC,
    )

    q_square = df_square.iloc[0]["circularity_q"]
    q_many = df_many.iloc[0]["circularity_q"]

    # 정사각형의 등주 지수는 정확히 π/4 — 평면 투영과 신발끈 계산이 맞다는 강한 확인이다.
    assert q_square == pytest.approx(math.pi / 4, abs=1e-3)
    assert q_many > 0.99             # 64각형은 사실상 원
    assert q_square < q_many
    assert q_many <= 1.0             # 등주 부등식상 1을 넘을 수 없다


def test_r9d_circularity_q_is_zero_for_pure_out_and_back():
    """면적이 0인 완전 왕복은 Q=0 — 퇴화 경로가 자연스럽게 바닥값을 받는다."""
    graph = nx.Graph()
    graph.add_edge("A", "B", length=1000)
    graph.nodes["A"].update(lat=37.5, lon=127.0)
    graph.nodes["B"].update(lat=37.51, lon=127.0)

    df = bm.run_benchmark(
        [FixedPathSolver("OutAndBack", path=["A", "B", "A"])], graph, "A", "A", {},
        timeout_sec=TEST_TIMEOUT_SEC,
    )

    assert df.iloc[0]["circularity_q"] == 0.0


@pytest.mark.parametrize(
    "path, with_coords, reason",
    [
        (["A", "B", "C"], True, "닫히지 않은 경로는 면적이 정의되지 않는다"),
        (["A", "B", "C", "A"], False, "좌표가 없으면 면적을 못 구한다"),
    ],
)
def test_r9e_circularity_q_is_none_when_undefined(path, with_coords, reason):
    graph = nx.Graph()
    for u, v in [("A", "B"), ("B", "C"), ("C", "A")]:
        graph.add_edge(u, v, length=1000)
    if with_coords:
        for node, (lat, lon) in {"A": (37.5, 127.0), "B": (37.51, 127.0), "C": (37.505, 127.01)}.items():
            graph.nodes[node].update(lat=lat, lon=lon)

    df = bm.run_benchmark(
        [FixedPathSolver("Undefined", path=path)], graph, "A", "A", {}, timeout_sec=TEST_TIMEOUT_SEC,
    )

    assert pd.isna(df.iloc[0]["circularity_q"]), reason


@pytest.mark.parametrize("builder", ["ok", "failed"])
def test_c1_every_row_builder_emits_exactly_result_columns(builder):
    """행 생성 경로가 RESULT_COLUMNS와 정확히 일치하는 키 집합을 낸다.

    컬럼이 늘 때마다 러너 4종 중 일부가 빠져 전 행 NaN이 되던 문제(2026-09-10)를
    구조적으로 막는 회귀 테스트 — _empty_row()를 거치지 않는 행 생성이 새로 생기면 깨진다.
    """
    solver = FixedPathSolver("RowShape", path=["A", "B", "A"])
    if builder == "ok":
        result = bm_results.validate_solver_result({"paths": [["A", "B", "A"]], "cost": 1.0})
        row = bm_results.build_result_row(solver, None, {"target_km": 3.0}, 0.1, result)
    else:
        row = bm_results.failed_row(solver, "failed", 0.1, "boom", 3.0)

    assert set(row) == set(bm_results.RESULT_COLUMNS)


def test_c2_runner_task_produces_the_same_row_shape_as_the_cli_path():
    """러너 4종이 쓰는 run_solver_task()와 CLI 경로(_run_single)가 같은 스키마를 낸다."""
    solver = FixedPathSolver("Shared", path=["A", "B", "A"])
    params = {"target_km": 3.0}

    runner_row = bm_results.run_solver_task(solver, None, "A", "A", params)
    cli_df = bm.run_benchmark([solver], None, "A", "A", params, timeout_sec=TEST_TIMEOUT_SEC)

    assert set(runner_row) == set(cli_df.columns)
    assert runner_row["status"] == cli_df.iloc[0]["status"] == "ok"


@pytest.mark.parametrize(
    "path, target_km, expect_passed, expect_reason",
    [
        (["A", "B", "C", "D", "A"], 4.0, True, None),           # 4km 루프, 편차 0
        (["A", "B", "C", "D", "A"], 6.0, False, "distance_deviation_km"),
        (["A", "B", "A"], 2.0, False, "repeated_edge_ratio"),   # 단순 왕복 = 0.5 > 0.35
    ],
)
def test_d1_gate_uses_only_final_path_observations(path, target_km, expect_passed, expect_reason):
    """합격 게이트는 최종 경로 관측값(거리 편차·재통행·폐합·잔가시)만으로 판정한다."""
    graph = nx.Graph()
    for u, v in [("A", "B"), ("B", "C"), ("C", "D"), ("D", "A")]:
        graph.add_edge(u, v, length=1000)

    df = bm.run_benchmark(
        [FixedPathSolver("Gated", path=path)], graph, "A", "A", {"target_km": target_km},
        timeout_sec=TEST_TIMEOUT_SEC,
    )
    row = df.iloc[0]

    assert bool(row["passed"]) is expect_passed
    if expect_reason is None:
        assert pd.isna(row["gate_failed_on"])
    else:
        assert expect_reason in row["gate_failed_on"]


def test_d2_gate_is_not_applied_to_oneway_rows():
    """편도 행은 게이트 대상이 아니다 — 닫히면 오히려 틀렸고, target_km을 아예 보지 않는
    알고리즘(A*/Dijkstra)도 섞여 있어 같은 기준이 무의미하다."""
    graph = nx.Graph()
    graph.add_edge("A", "B", length=1000)

    df = bm.run_benchmark(
        [FixedPathSolver("Oneway", path=["A", "B"])], graph, "A", "B", {"target_km": 1.0},
        timeout_sec=TEST_TIMEOUT_SEC,
    )

    assert pd.isna(df.iloc[0]["passed"])
    assert pd.isna(df.iloc[0]["gate_failed_on"])


def test_d3_failed_rows_are_gate_failures_on_circular_runs():
    df = bm.run_benchmark(
        [RaisingSolver("Boom")], None, "A", "A", {"target_km": 3.0}, timeout_sec=TEST_TIMEOUT_SEC,
    )
    row = df.iloc[0]

    assert row["status"] == "failed"
    assert bool(row["passed"]) is False
    assert row["gate_failed_on"] == "status"


def test_d4_gate_ignores_waypoint_derived_diagnostics():
    """경유지 분해 기반 지표(feasible / is_degenerate_loop)가 나빠도 게이트는 통과한다.

    경유지는 사용자와 약속한 대상이 아니라 순환 경로를 만들기 위한 내부 수단이므로,
    최종 경로가 거리·겹침 기준을 만족하면 정상 해다(2026-09-10 결정).
    """
    row = {
        "status": "ok",
        "is_closed_loop": True,
        "distance_deviation_km": 0.1,
        "repeated_edge_ratio": 0.0,
        "spike_count": 0,
        # 아래는 전부 "나쁜" 값이지만 게이트가 보지 않는 항목이다.
        "feasible": False,
        "is_degenerate_loop": True,
        "num_waypoints_used": 6,
        "effective_waypoints_used": 1,
        "segment_balance_ratio": 0.01,
    }

    passed, reason = bm_results.evaluate_gate(row, circular=True)

    assert passed is True
    assert reason is None


def test_f1_refinement_cli_knobs_match_the_solver_and_engine_contracts():
    """CLI 플래그 목록이 solver의 노브 표·엔진의 허용 정제 목록과 어긋나지 않는지 고정.

    어긋난 채로 값을 실어 보내면 엔진 생성자가 ValueError로 막아 런타임에야 드러난다.
    """
    from benchmarks.solvers.grasp_waypoint_solver import _REFINEMENT_PARAM_KEYS
    from src.route_engine.engines.waypoint_refinement import OPTIONS_AWARE_REFINEMENTS

    for refinement, knob, _, _ in bm._REFINEMENT_CLI_KNOBS:
        assert refinement in OPTIONS_AWARE_REFINEMENTS, f"{refinement}는 옵션 주입을 받지 않는다"
        assert knob in _REFINEMENT_PARAM_KEYS[refinement], f"{refinement}_{knob}는 solver가 모르는 노브"


def test_f2_refinement_knobs_only_reach_params_when_explicitly_given():
    """지정하지 않은 노브는 params에 들어가지 않는다 — 엔진 기본값이 그대로 쓰여야 한다."""
    args = bm.parse_args(["--algo", "grasp-wp-alns"])
    assert bm.refinement_params_from_args(args) == {}

    args = bm.parse_args([
        "--algo", "grasp-wp-alns", "--alns-iterations", "60", "--vns-max-shake-level", "3",
    ])
    assert bm.refinement_params_from_args(args) == {"alns_iterations": 60, "vns_max_shake_level": 3}


def test_f3_refinement_knob_params_are_understood_by_the_solver_adapter():
    """CLI가 만든 params 키를 solver 어댑터가 그대로 정제 설정으로 되돌린다."""
    from benchmarks.solvers.grasp_waypoint_solver import _refinement_options_from_params

    args = bm.parse_args([
        "--algo", "grasp-wp-alns", "--alns-iterations", "60", "--alns-cooling-rate", "0.9",
    ])
    params = bm.refinement_params_from_args(args)

    assert _refinement_options_from_params("alns", params) == {"iterations": 60, "cooling_rate": 0.9}
    assert _refinement_options_from_params("vns", params) is None


def test_e1_seed_axis_only_repeats_solvers_that_read_the_seed():
    """시드를 읽지 않는 solver까지 반복하면 실행 시간만 늘어난다."""
    from benchmarks import run_all_scenarios as ras

    # grasp-circular 케이스는 2026-09-11 레지스트리에서 제외된 키라 뺐다 — 미등록 키로도
    # 통과해버려 존재하지 않는 solver를 검증하고 있었다. 명제는 beam-wp로 충분하다.
    tasks = ras._scenario_tasks(["grasp-wp-alns", "beam-wp"])
    by_algo = {}
    for key, seed in tasks:
        by_algo.setdefault(key, []).append(seed)

    assert len(by_algo["grasp-wp-alns"]) == len(bm_config.BENCHMARK_SEEDS)
    assert by_algo["beam-wp"] == [None]


def test_e2_seed_sensitive_solvers_are_all_registered():
    """오타로 레지스트리에 없는 키가 들어가면 그 solver는 조용히 1회만 돌게 된다."""
    assert bm.SEED_SENSITIVE_SOLVERS <= set(bm.SOLVER_REGISTRY)


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
    # 원형성(circularity_q)은 노드 좌표가 있어야 계산된다 — 대략 정사각형에 가까운 배치.
    for node, (lat, lon) in {
        "Start": (37.5000, 127.0000),
        "N1": (37.5000, 127.0080),
        "N2": (37.5063, 127.0080),
        "N3": (37.5063, 127.0000),
    }.items():
        graph.nodes[node]["lat"] = lat
        graph.nodes[node]["lon"] = lon

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
    assert row["repeated_edge_ratio"] == 0.0
    # 사각형 루프는 같은 둘레의 원보다 면적이 작으므로 Q는 1보다 확실히 낮되,
    # 면적이 0인 왕복 퇴화와는 뚜렷이 구분되는 값이어야 한다.
    assert 0.5 < row["circularity_q"] < 1.0
