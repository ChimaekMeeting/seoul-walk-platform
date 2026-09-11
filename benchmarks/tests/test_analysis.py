"""
benchmarks/tests/test_analysis.py

H(대리 지표 검증)·I(임계값 근거) 분석 스크립트 검증.

이 두 스크립트의 존재 이유는 "데이터가 말해주지 않는 것을 말했다고 착각하지 않는 것"이다.
그래서 상관이 실제로 있을 때 잡아내는지뿐 아니라, 표본이 부족하거나 관계가 없을 때
단정하지 않는지도 함께 고정한다.
"""

import numpy as np
import pandas as pd
import pytest

from benchmarks import analyze_circularity_proxy as proxy
from benchmarks import analyze_thresholds as thresholds


def _rows(n=40, *, correlated=True, preserved=True, seed=7):
    """분리도와 원형성이 (선택적으로) 단조 관계인 합성 데이터."""
    rng = np.random.default_rng(seed)
    separation = rng.uniform(600, 1500, n)
    circularity = (
        separation / 3000 + rng.normal(0, 0.01, n) if correlated else rng.uniform(0.2, 0.8, n)
    )
    return pd.DataFrame({
        "algorithm": "A",
        "status": "ok",
        "target_km": 3.0,
        "waypoint_separation_m": separation,
        "segment_balance_ratio": rng.uniform(0.3, 0.9, n),
        "waypoint_angle_diff_deg": rng.uniform(30, 150, n),
        "circularity_q": circularity,
        "repeated_edge_ratio": rng.uniform(0.0, 0.6, n),
        "distance_deviation_km": rng.uniform(0.0, 0.4, n),
        "spike_count": 0,
        "num_waypoints_used": 2,
        "effective_waypoints_used": 2 if preserved else 1,
        "waypoints_lost_clean": 0 if preserved else 1,
        "waypoints_lost_repeated": 0,
        "selection_status": "feasible",
        "passed": True,
        "astar_calls": 200,
    })


def _separation_row(result: pd.DataFrame) -> pd.Series:
    match = result[(result["구분"] == "전체") & (result["지표"].str.startswith("분리도"))]
    return match.iloc[0]


# ── H ────────────────────────────────────────────────────────────────────

def test_h1_separation_ratio_is_normalized_by_target_distance():
    """분리도는 절대 거리가 아니라 target 대비 비율로 봐야 target_km이 섞여도 비교된다."""
    work = proxy.prepare(_rows(10))

    expected = work["waypoint_separation_m"] / 3000
    assert np.allclose(work["separation_ratio"], expected)


def test_h2_waypoint_preservation_flag_marks_pruned_rows():
    work = proxy.prepare(_rows(10, preserved=False))

    assert not work["waypoints_preserved"].any()


def test_h3_correlation_is_detected_when_it_exists():
    work = proxy.prepare(_rows(60, correlated=True))

    overall = _separation_row(proxy.correlations(work))

    assert overall["spearman"] > 0.9
    assert overall["0_제외"] == "예"


def test_h4_no_correlation_is_not_claimed_as_one():
    """관계가 없으면 신뢰구간이 0을 포함해야 한다 — 없는 관계를 있다고 말하면 안 된다."""
    work = proxy.prepare(_rows(60, correlated=False, seed=11))

    overall = _separation_row(proxy.correlations(work))

    assert overall["0_제외"] == "아니오"


def test_h5_small_samples_produce_no_correlation_at_all():
    """표본이 적으면 상관계수를 내지 않는다(우연한 큰 값이 결론으로 둔갑하는 것을 막는다)."""
    work = proxy.prepare(_rows(4))

    result = proxy.correlations(work)

    assert result["spearman"].isna().all()


def test_h6_verdict_refuses_to_conclude_without_evidence():
    work = proxy.prepare(_rows(60, correlated=False, seed=11))

    message = proxy.verdict(proxy.correlations(work))

    assert "목적함수로 승격하지 마세요" in message


def test_h7_prune_criterion_report_follows_the_lost_waypoint_split():
    work = proxy.prepare(_rows(10, preserved=False))

    message = proxy.prune_criterion_report(work)

    assert "전환을 검토할 근거가 있습니다" in message


def test_h8_waypoint_loss_report_pairs_declared_and_effective_counts():
    work = proxy.prepare(_rows(10, preserved=False))

    report = proxy.waypoint_loss_report(work)

    assert report.iloc[0]["선언N"] == 2
    assert report.iloc[0]["실제통과_평균"] == 1
    assert report.iloc[0]["보존율"] == 0.0


def test_h9_bootstrap_ci_is_reproducible():
    """같은 입력이면 같은 구간이 나와야 한다 — 시드가 고정돼 있다."""
    work = proxy.prepare(_rows(40))

    first = proxy.bootstrap_ci(work["separation_ratio"], work[proxy.GROUND_TRUTH])
    second = proxy.bootstrap_ci(work["separation_ratio"], work[proxy.GROUND_TRUTH])

    assert first == second
    assert first[0] is not None and first[0] <= first[1]


def test_h10_spearman_is_computed_without_scipy_and_handles_ties():
    """pandas의 corr(method="spearman")은 scipy.stats.spearmanr를 import하는데 이 저장소에는
    scipy가 없다. 순위 변환 후 pearson으로 직접 계산하며 동점은 평균 순위로 처리된다.

    scipy 의존을 다시 들이면 이 테스트가 아니라 임포트에서 깨지므로, 여기서는 계산 결과가
    표준 Spearman의 성질(단조 관계에서 정확히 1, 비선형이면 Pearson보다 큼)을 갖는지를 고정한다.
    """
    x = pd.Series(range(1, 11), dtype=float)
    y = x ** 3  # 완전한 단조 증가지만 비선형

    assert proxy._corr(x, y, "spearman") == pytest.approx(1.0)
    assert proxy._corr(x, y, "pearson") < 1.0

    tied = pd.Series([1, 1, 1, 2, 2, 3, 3, 4, 5, 6], dtype=float)
    assert proxy._corr(tied, x, "spearman") is not None


def test_h11_missing_ground_truth_column_fails_with_a_clear_message():
    """circularity_q가 없는 구 스키마 CSV는 트레이스백이 아니라 안내로 끝나야 한다."""
    old_schema = pd.DataFrame([{"algorithm": "A", "status": "ok", "target_km": 3.0}])

    with pytest.raises(SystemExit) as error:
        proxy.prepare(old_schema)

    assert "circularity_q" in str(error.value)
    assert "격자를 다시 실행하세요" in str(error.value)


# ── I ────────────────────────────────────────────────────────────────────

def test_i1_degenerate_sweep_marks_the_current_threshold():
    work = thresholds.successful(_rows(40))

    sweep = thresholds.degenerate_threshold_sweep(work)

    current = sweep[sweep["현재값"] == "←"]
    assert len(current) == 1
    assert current.iloc[0]["임계값"] == thresholds.MAX_REPEATED_EDGE_RATIO


def test_i2_gate_quantiles_report_current_pass_rate():
    work = thresholds.successful(_rows(40))

    table = thresholds.gate_threshold_quantiles(work)
    deviation = table[table["지표"] == "distance_deviation_km"].iloc[0]

    assert 0.0 <= deviation["현재값_통과율"] <= 1.0
    assert deviation["q100"] >= deviation["q50"]


def test_i3_separation_distribution_reports_against_the_current_filter():
    work = thresholds.successful(_rows(40))

    table = thresholds.separation_distribution(work)

    assert table.iloc[0]["현재_문턱"] == 0.20
    assert table.iloc[0]["최소"] <= table.iloc[0]["중앙값"] <= table.iloc[0]["최대"]


def test_i4_recommendation_refuses_when_nothing_is_flagged():
    """재통행이 낮은 데이터만 있으면 임계값을 제안하지 않는다."""
    work = thresholds.successful(_rows(40))
    work["repeated_edge_ratio"] = 0.0

    message = thresholds.recommend_degenerate_threshold(
        thresholds.degenerate_threshold_sweep(work)
    )

    assert "다시 실행하세요" in message


def test_i5_main_states_what_it_cannot_answer(tmp_path, capsys):
    """필터가 걸러낸 후보의 품질은 CSV에 남지 않는다 — 그 한계를 반드시 출력해야 한다."""
    raw = tmp_path / "raw.csv"
    _rows(40).to_csv(raw, index=False)

    thresholds.main([str(raw), "--out-dir", str(tmp_path / "out")])

    captured = capsys.readouterr().out
    assert "판단할 수 없습니다" in captured
    assert "GraspConfig 주입 경로" in captured


def test_i6_fallback_rows_are_compared_against_feasible_ones():
    """제약이 품질을 지켜주는지 보려면 fallback과 feasible을 나란히 봐야 한다."""
    work = thresholds.successful(_rows(20))
    work.loc[work.index[:10], "selection_status"] = "fallback_distance"

    table = thresholds.fallback_quality(work)

    assert set(table["selection_status"]) == {"feasible", "fallback_distance"}
    assert table["n"].sum() == 20
