"""
benchmarks/tests/test_aggregate_results.py

집계기가 "실패를 숨기지 않는가"를 중심으로 검증한다. 평균만 보면 어려운 조건에서
실패하는 알고리즘이 유리해 보이는 함정이 이 스크립트가 존재하는 이유이므로,
그 함정을 실제로 드러내는지를 테스트로 고정한다.
"""

import pandas as pd
import pytest

from benchmarks import aggregate_results as agg
from benchmarks.stats import percentile


def _row(algorithm, start_node, seed, *, status="ok", passed=True,
         deviation=0.1, repeated=0.0, elapsed=1.0, astar=100, circularity=0.5,
         cache_hits=0, pool_misses=10):
    return {
        "algorithm": algorithm, "start_node": start_node, "target_km": 3.0, "seed": seed,
        "status": status, "passed": passed,
        "distance_deviation_km": deviation, "repeated_edge_ratio": repeated,
        "spike_count": 0, "circularity_q": circularity,
        "elapsed_sec": elapsed, "find_path_sec": None,
        "astar_calls": astar, "cache_hits": cache_hits, "pool_cache_misses": pool_misses,
        "waypoint_separation_m": 800.0, "segment_balance_ratio": 0.6,
    }


def test_g1_condition_columns_exclude_algorithm_and_seed():
    """조건은 '같은 문제 인스턴스'이지 '무엇을 몇 번 돌렸는가'가 아니다."""
    df = pd.DataFrame([_row("A", 1, 42)])

    columns = agg.condition_columns(df)

    assert "start_node" in columns and "target_km" in columns
    assert "algorithm" not in columns and "seed" not in columns


def test_g2_sweep_knob_columns_are_part_of_the_condition():
    """스윕에서는 파라미터 설정도 조건의 일부다 — 설정이 다르면 다른 조건이다."""
    df = pd.DataFrame([{**_row("A", 1, 42), "alns_iterations": 60, "vns_max_shake_level": 2}])

    columns = agg.condition_columns(df)

    assert "alns_iterations" in columns and "vns_max_shake_level" in columns


def test_g2b_result_columns_are_never_treated_as_conditions():
    """alns_operator_stats는 이름이 노브 패턴에 걸리지만 실행 결과로 나온 JSON이다.

    조건으로 잡으면 행마다 값이 달라 모든 조건이 1행씩으로 쪼개지고, 짝지은 비교와
    승률이 통째로 무의미해진다(2026-09-10 실측 CSV에서 실제로 발생).
    """
    df = pd.DataFrame([{
        **_row("A", 1, 42),
        "alns_operator_stats": '{"alns_calls": 23}',
        "alns_iterations": 60,
    }])

    columns = agg.condition_columns(df)

    assert "alns_operator_stats" not in columns
    assert "alns_iterations" in columns  # 진짜 노브는 그대로 남는다


def test_g3_pass_rate_counts_failures_but_quality_mean_does_not():
    """실패 행은 분모에 남고(pass_rate), 품질 평균에서는 빠진다 — 그래서 둘을 같이 읽어야 한다."""
    rows = [
        _row("A", 1, 1, deviation=0.1),
        _row("A", 1, 2, status="failed", passed=False, deviation=None),
    ]
    result = agg.per_condition(pd.DataFrame(rows))

    assert result.iloc[0]["n_runs"] == 2
    assert result.iloc[0]["pass_rate"] == 0.5
    assert result.iloc[0]["distance_deviation_km_mean"] == pytest.approx(0.1)


def test_g4_timeout_rows_are_excluded_from_time_stats():
    """타임아웃의 elapsed_sec은 실측이 아니라 제한시간이므로 시간 평균을 오염시키면 안 된다."""
    rows = [
        _row("A", 1, 1, elapsed=2.0),
        _row("A", 1, 2, status="timeout", passed=False, elapsed=400.0),
    ]
    result = agg.per_condition(pd.DataFrame(rows))

    assert result.iloc[0]["n_timeout"] == 1
    assert result.iloc[0]["elapsed_sec_mean"] == pytest.approx(2.0)


@pytest.mark.parametrize(
    "column, higher_is_better, values, expected_worst",
    [
        ("distance_deviation_km", False, [0.1, 0.9], 0.9),  # 낮을수록 좋음 → 최악은 최대
        ("circularity_q", True, [0.2, 0.8], 0.2),           # 높을수록 좋음 → 최악은 최소
    ],
)
def test_g5_worst_follows_each_metrics_direction(column, higher_is_better, values, expected_worst):
    metric = agg.Metric(column, higher_is_better=higher_is_better)

    assert metric.worst(pd.Series(values)) == expected_worst


def test_g6_paired_comparison_drops_conditions_where_any_algorithm_failed_entirely():
    """한 알고리즘이 전부 실패한 조건은 짝지은 비교에서 빠진다 — 안 그러면 그 알고리즘이
    쉬운 조건만으로 평가된다."""
    rows = [
        _row("A", 1, 1), _row("B", 1, 1),                                   # 조건 1: 둘 다 성공
        _row("A", 2, 1), _row("B", 2, 1, status="failed", passed=False),    # 조건 2: B 전멸
    ]
    condition_df = agg.per_condition(pd.DataFrame(rows))

    paired, total, kept = agg.paired_conditions(condition_df)

    assert total == 2 and kept == 1
    assert set(paired["start_node"]) == {1}


def test_g6b_conditions_with_nan_keys_are_not_silently_dropped():
    """조건 키에 NaN이 섞여도 짝지은 비교에서 조용히 사라지면 안 된다.

    파이썬 집합 멤버십으로 필터하면 `nan in {nan}`이 False라 해당 조건이 통째로
    탈락한다(2026-09-10). merge 기반으로 바꾼 뒤의 회귀 테스트.
    """
    rows = [
        {**_row("A", 1, 1), "alns_iterations": None},
        {**_row("B", 1, 1), "alns_iterations": None},
    ]
    condition_df = agg.per_condition(pd.DataFrame(rows))

    paired, total, kept = agg.paired_conditions(condition_df)

    assert total == 1 and kept == 1
    assert len(paired) == 2


def test_g7_win_rate_is_decided_by_circularity_not_by_the_gate():
    """순위 1순위는 정규화 원형성이다(2026-09-11 규칙 변경).

    게이트 4항목 중 3항목이 정상 동작에서 상수라, pass_rate를 1순위에 두면 전 알고리즘이
    동점이 되어 2순위가 단독으로 승자를 정했다. 게이트는 참가 자격으로 내렸다.
    """
    rows = [
        # 같은 조건에서 B가 더 원형이다(거리편차는 동일) → B가 이겨야 한다
        _row("A", 1, 1, circularity=0.2), _row("A", 1, 2, circularity=0.2),
        _row("B", 1, 1, circularity=0.6), _row("B", 1, 2, circularity=0.6),
    ]
    condition_df = agg.per_condition(agg.add_derived_columns(pd.DataFrame(rows)))

    wins = agg.win_rates(condition_df)

    assert wins.iloc[0]["algorithm"] == "B"
    assert wins.iloc[0]["win_rate"] == 1.0


def test_g7b_gate_failure_removes_a_candidate_from_the_ranking():
    """게이트는 순위 항목이 아니라 참가 자격 — 전부 불합격한 후보는 경쟁에서 빠진다.

    품질 평균은 성공 행만으로 계산되므로, 전부 불합격한 알고리즘을 남겨두면 '쉬운 시드에서만
    좋았던 값'으로 이길 수 있다.
    """
    rows = [
        # A는 더 원형이지만 그 조건에서 한 번도 게이트를 통과하지 못했다
        _row("A", 1, 1, circularity=0.9, passed=False),
        _row("A", 1, 2, circularity=0.9, passed=False),
        _row("B", 1, 1, circularity=0.3), _row("B", 1, 2, circularity=0.3),
    ]
    condition_df = agg.per_condition(agg.add_derived_columns(pd.DataFrame(rows)))

    wins = agg.win_rates(condition_df)

    assert set(wins["algorithm"]) == {"B"}


def test_g8_budget_report_uses_search_work_not_astar_calls():
    """astar_calls는 캐시 조회와 cutoff SSSP를 세지 않아 계산량을 오판한다(실측 R²=0.238).

    search_work가 두 연산을 공통 단위로 환산한 값이며, 예산 경고는 그쪽을 기준으로 한다.
    """
    rows = [
        _row("Cheap", 1, 1, astar=100, cache_hits=0, pool_misses=0),
        _row("Expensive", 1, 1, astar=100, cache_hits=0, pool_misses=100),
    ]
    algorithm_df = agg.per_algorithm(agg.add_derived_columns(pd.DataFrame(rows)))

    report = agg.budget_report(algorithm_df)

    # astar_calls는 둘 다 100으로 같지만, SSSP 100회(=2,750 조회 상당)가 예산 차이를 만든다
    assert "search_work" in report
    assert "28.5배" in report
    assert "재실행" in report


def test_g8b_budget_report_warns_when_only_astar_calls_are_available():
    """search_work를 만들 수 없는 구 CSV에서는 astar_calls로 물러서되 한계를 밝힌다."""
    rows = [
        {k: v for k, v in _row("Cheap", 1, 1, astar=100).items() if k != "cache_hits"},
        {k: v for k, v in _row("Expensive", 1, 1, astar=5000).items() if k != "cache_hits"},
    ]
    algorithm_df = agg.per_algorithm(agg.add_derived_columns(pd.DataFrame(rows)))

    report = agg.budget_report(algorithm_df)

    assert "50.0배" in report
    assert "계산량을 크게 오판" in report


def test_g9_percentile_keeps_nearest_rank_semantics_after_the_move():
    """waypoint_overlap_audit.py에서 옮겨온 구현이 그대로인지 확인(정의는 한 벌만 존재)."""
    from benchmarks.runner import waypoint_overlap_audit

    assert waypoint_overlap_audit.percentile is percentile
    assert percentile([1, 2, 3, 4, 5], 0.95) == 5
    assert percentile([1, 2, 3, 4], 0.5) == 2


def test_g10_p95_is_computed_on_the_bad_tail_of_each_metric():
    """낮을수록 좋은 지표는 상위 꼬리가, 높을수록 좋은 지표는 하위 꼬리가 '나쁜 쪽'이다."""
    values = pd.Series([0.1, 0.2, 0.3, 0.4, 0.9])

    lower_better = agg.Metric("distance_deviation_km", higher_is_better=False)
    higher_better = agg.Metric("circularity_q", higher_is_better=True)

    assert lower_better.p95(values) == 0.9
    assert higher_better.p95(values) == 0.1


def test_g11_end_to_end_main_writes_aggregate_csvs(tmp_path, capsys):
    """CLI 경로가 실제로 돌고 집계 CSV 3종을 남기는지 확인."""
    rows = [
        _row("A", 1, 1), _row("A", 1, 2), _row("B", 1, 1), _row("B", 1, 2),
        _row("A", 2, 1), _row("B", 2, 1, status="failed", passed=False),
    ]
    raw = tmp_path / "raw.csv"
    pd.DataFrame(rows).to_csv(raw, index=False)
    out_dir = tmp_path / "out"

    agg.main([str(raw), "--out-dir", str(out_dir)])

    assert (out_dir / "aggregate_by_condition.csv").exists()
    assert (out_dir / "aggregate_by_algorithm.csv").exists()
    assert (out_dir / "aggregate_win_rates.csv").exists()

    captured = capsys.readouterr().out
    assert "짝지은 비교" in captured
    assert "pass_rate와 함께 읽으세요" in captured  # 조건 2가 빠졌으므로 경고가 떠야 한다


def test_g13_derived_columns_convert_two_different_operations_to_one_unit():
    """astar_calls와 pool_cache_misses는 단위가 다르다 — SSSP 1회는 A* 1회가 아니다."""
    rows = [_row("A", 1, 1, astar=100, cache_hits=900, pool_misses=10)]

    work = agg.add_derived_columns(pd.DataFrame(rows))

    assert work.iloc[0]["path_lookups"] == 1000
    assert work.iloc[0]["search_work"] == pytest.approx(1000 + 27.5 * 10)


def test_g13b_rows_without_any_counter_stay_unmeasured_not_zero():
    """레거시 solver는 두 카운터를 아예 보고하지 않는다 — 0으로 채우면 '가장 싼 알고리즘'이 된다."""
    rows = [_row("Legacy", 1, 1, astar=None, cache_hits=None)]

    work = agg.add_derived_columns(pd.DataFrame(rows))

    assert pd.isna(work.iloc[0]["path_lookups"])


def test_g14_circularity_is_normalized_within_each_condition():
    """도보망의 Q 상한은 조건마다 다르고 이론값이 없다 — 같은 조건 안에서의 상대 위치로 본다."""
    rows = [
        _row("A", 1, 1, circularity=0.3), _row("B", 1, 1, circularity=0.6),  # 조건 1: 최대 0.6
        _row("A", 2, 1, circularity=0.2), _row("B", 2, 1, circularity=0.4),  # 조건 2: 최대 0.4
    ]

    work = agg.add_derived_columns(pd.DataFrame(rows)).set_index(["algorithm", "start_node"])

    assert work.loc[("A", 1), "circularity_q_rel"] == pytest.approx(0.5)
    assert work.loc[("A", 2), "circularity_q_rel"] == pytest.approx(0.5)  # 절대값은 달라도 상대는 같다
    assert work.loc[("B", 1), "circularity_q_rel"] == pytest.approx(1.0)


def test_g14b_failed_rows_do_not_become_the_normalization_denominator():
    """실패 행의 circularity_q는 비어 있다 — 분모는 성공 행에서만 나와야 한다."""
    rows = [
        _row("A", 1, 1, circularity=0.4),
        _row("B", 1, 1, status="failed", passed=False, circularity=None),
    ]

    work = agg.add_derived_columns(pd.DataFrame(rows))

    assert work.iloc[0]["circularity_q_rel"] == pytest.approx(1.0)


def test_g15_survival_counts_failures_in_the_denominator():
    """실패는 '예산 안에 든 것'이 아니다 — 분모에서 빼면 생존율이 부풀려진다."""
    rows = [
        _row("A", 1, 1, elapsed=2.0),
        _row("A", 1, 2, elapsed=90.0),
        _row("A", 1, 3, status="failed", passed=False, elapsed=1.0),
    ]

    table = agg.survival_by_budget(pd.DataFrame(rows), budgets=(5.0, 60.0)).iloc[0]

    assert table["n_runs"] == 3
    assert table["survive_5s"] == pytest.approx(1 / 3, abs=1e-4)  # 표에 싣는 값이라 4자리로 반올림된다
    assert table["elapsed_worst"] == 90.0  # 동기 요청에서 예산을 정하는 것은 최악값이다


def test_g16_quality_under_budget_exposes_survivorship_bias():
    """예산이 빡빡하면 쉬운 조건만 남는다 — 품질과 생존율을 같은 표에 함께 낸다."""
    rows = [
        _row("A", 1, 1, elapsed=2.0, deviation=0.01),   # 빠르고 좋은 행만 예산 안에 든다
        _row("A", 1, 2, elapsed=90.0, deviation=0.90),
    ]

    table = agg.quality_under_budget(agg.add_derived_columns(pd.DataFrame(rows)), 5.0).iloc[0]

    assert table["survival"] == pytest.approx(0.5)
    assert table["distance_deviation_km_mean"] == pytest.approx(0.01)


def test_g17_paired_permutation_test_is_exact_for_small_condition_counts():
    """조건이 적을 때 평균 차이만 보고 '더 낫다'고 말하는 것을 막는 장치다.

    조건 2개에서 한쪽이 매번 이겨도 부호 조합이 4가지뿐이라 p=0.5 — 유의하지 않다.
    """
    rows = []
    for start_node in (1, 2):
        rows += [_row("A", start_node, 1, circularity=0.6), _row("B", start_node, 1, circularity=0.3)]
    condition_df = agg.per_condition(agg.add_derived_columns(pd.DataFrame(rows)))

    tests = agg.paired_tests(condition_df)

    assert len(tests) == 1
    assert tests.iloc[0]["n_conditions"] == 2
    assert tests.iloc[0]["평균차(A-B)"] > 0
    assert tests.iloc[0]["p_value"] == pytest.approx(0.5)
    assert tests.iloc[0]["유의(α=0.05)"] == "아니오"


def test_g17b_permutation_test_detects_a_consistent_difference_given_enough_conditions():
    """조건이 충분히 많고 한쪽이 매번 이기면 유의해진다(2^10 = 1,024가지 중 2가지)."""
    rows = []
    for start_node in range(1, 11):
        rows += [_row("A", start_node, 1, circularity=0.6), _row("B", start_node, 1, circularity=0.3)]
    condition_df = agg.per_condition(agg.add_derived_columns(pd.DataFrame(rows)))

    tests = agg.paired_tests(condition_df)

    assert tests.iloc[0]["p_value"] == pytest.approx(2 / 1024)
    assert tests.iloc[0]["유의(α=0.05)"] == "예"


def test_g18_algorithm_summary_reports_independent_sample_count():
    """n_runs는 독립 표본 수가 아니다 — 조건 10개 × 시드 10개는 독립 단위가 10개다."""
    rows = [_row("A", start, seed) for start in (1, 2) for seed in (1, 2, 3)]

    summary = agg.per_algorithm(pd.DataFrame(rows)).iloc[0]

    assert summary["n_runs"] == 6
    assert summary["n_conditions"] == 2
    assert summary["n_seeds_per_condition"] == 3


def test_g12_old_schema_csv_warns_instead_of_crashing(tmp_path, capsys):
    """게이트 이전에 만들어진 CSV(passed/circularity_q 없음)도 죽지 않고 경고만 낸다."""
    rows = [{"algorithm": "A", "start_node": 1, "target_km": 3.0, "seed": 1,
             "status": "ok", "distance_deviation_km": 0.1, "elapsed_sec": 1.0}]
    raw = tmp_path / "old.csv"
    pd.DataFrame(rows).to_csv(raw, index=False)

    agg.main([str(raw), "--out-dir", str(tmp_path / "out")])

    captured = capsys.readouterr().out
    assert "passed 컬럼이 없습니다" in captured
    assert "다시 실행하세요" in captured
