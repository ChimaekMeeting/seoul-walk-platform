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
         deviation=0.1, repeated=0.0, elapsed=1.0, astar=100, circularity=0.5):
    return {
        "algorithm": algorithm, "start_node": start_node, "target_km": 3.0, "seed": seed,
        "status": status, "passed": passed,
        "distance_deviation_km": deviation, "repeated_edge_ratio": repeated,
        "spike_count": 0, "circularity_q": circularity,
        "elapsed_sec": elapsed, "find_path_sec": None,
        "astar_calls": astar, "pool_cache_misses": 10,
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


def test_g7_win_rate_follows_the_documented_ranking_rule():
    """순위는 pass_rate → 거리편차 → 재통행 순. 거리편차가 나빠도 게이트를 더 자주
    통과하면 이긴다."""
    rows = [
        # 조건 1: A가 게이트 통과율 우세(거리편차는 B가 좋음)
        _row("A", 1, 1, deviation=0.4), _row("A", 1, 2, deviation=0.4),
        _row("B", 1, 1, deviation=0.1), _row("B", 1, 2, deviation=0.1, status="failed", passed=False),
    ]
    condition_df = agg.per_condition(pd.DataFrame(rows))

    wins = agg.win_rates(condition_df)

    assert wins.iloc[0]["algorithm"] == "A"
    assert wins.iloc[0]["win_rate"] == 1.0


def test_g8_budget_report_warns_when_search_budgets_differ_widely():
    """예산이 크게 다르면 품질 비교가 '예산이 큰 쪽'을 고르게 된다 — 집계로는 못 고친다."""
    rows = [_row("Cheap", 1, 1, astar=100), _row("Expensive", 1, 1, astar=5000)]
    algorithm_df = agg.per_algorithm(pd.DataFrame(rows))

    report = agg.budget_report(algorithm_df)

    assert "50.0배" in report
    assert "재실행" in report


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
