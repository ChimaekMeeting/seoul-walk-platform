"""
benchmarks/aggregate_results.py

벤치마크 raw CSV를 알고리즘 결정에 쓸 수 있는 형태로 접는다(2026-09-10 신규, 이슈 G).

지금까지 러너들이 print하는 요약은 전부 평균뿐이었다. 확률적 알고리즘(GRASP·ALNS)을
평균만으로 비교하면 "평균은 좋지만 5회 중 1회 퇴화 경로를 내놓는" 알고리즘이 1등이 된다.
이 스크립트는 시드 반복을 접어 분산·최악값을 내고, 실패를 숨기지 않도록 게이트 통과율을
항상 함께 낸다.

━━ 순위 규칙 (코드보다 먼저 고정한다) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
결과를 보고 나서 기준을 고르는 일을 막기 위해, 알고리즘 순위는 아래 사전식 규칙으로만
정한다. 이 규칙을 바꾸려면 커밋 메시지에 근거를 남길 것.

    1) pass_rate 내림차순                  — 합격 게이트를 얼마나 자주 통과하는가
    2) distance_deviation_km 평균 오름차순 — 목표 거리를 얼마나 맞추는가
    3) repeated_edge_ratio 평균 오름차순   — 같은 길을 얼마나 덜 되짚는가

circularity_q는 아직 임계값·상관이 검증되지 않아(이슈 H) 순위에 넣지 않는다.
cost는 solver마다 정의가 달라 애초에 비교 대상이 아니다.

━━ 읽을 때 반드시 지킬 것 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 품질 평균은 성공한 실행만으로 계산된다. 어려운 조건에서 실패하는 알고리즘일수록
  쉬운 케이스만 남아 품질이 좋아 보이므로, pass_rate 없이 품질 평균만 읽지 말 것.
  그래서 "짝지은 비교"(모든 알고리즘이 성공한 조건으로만 한정) 표를 따로 낸다.
- 타임아웃 행의 elapsed_sec은 실제 소요가 아니라 제한시간에서 잘린(censored) 값이다.
  시간 통계에서는 제외하고, 몇 건이 잘렸는지 별도로 표기한다.
- 조건당 시드 10개에서 p95는 최댓값과 같아진다(stats.percentile docstring 참고).
  그래서 p95는 조건 단위가 아니라 알고리즘 전체를 모은 뒤에만 낸다.

실행:
    python -m benchmarks.aggregate_results all_scenarios_results.csv
    python -m benchmarks.aggregate_results benchmarks/alns_validation_results.csv \\
                                           benchmarks/min_separation_validation_results.csv
    python -m benchmarks.aggregate_results benchmarks/alns_sweep_results.csv --out-dir benchmarks/results
"""

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from benchmarks.results import RESULT_COLUMNS
from benchmarks.stats import percentile


@dataclass(frozen=True)
class Metric:
    """집계 대상 지표 하나.

    higher_is_better가 지표마다 다르기 때문에 "최악값"을 max로 고정할 수 없다 —
    distance_deviation_km의 최악은 최댓값이지만 circularity_q의 최악은 최솟값이다.
    censored_by_timeout은 타임아웃 행의 값이 실측이 아니라 제한시간이라는 표시다.
    """
    column: str
    higher_is_better: bool
    censored_by_timeout: bool = False

    def worst(self, series: pd.Series):
        return series.min() if self.higher_is_better else series.max()

    def p95(self, series: pd.Series):
        """나쁜 쪽 꼬리의 분위수. 낮을수록 좋은 지표는 상위 95%, 높을수록 좋은 지표는
        하위 5%가 '나쁜 쪽'이다."""
        values = series.dropna().tolist()
        if not values:
            return None
        return percentile(values, 0.05 if self.higher_is_better else 0.95)


# 1계층 게이트가 쓰는 관측값 + 원형성. 알고리즘 품질 비교의 본체다.
QUALITY_METRICS = (
    Metric("distance_deviation_km", higher_is_better=False),
    Metric("repeated_edge_ratio", higher_is_better=False),
    Metric("spike_count", higher_is_better=False),
    Metric("circularity_q", higher_is_better=True),
)

# 3계층 비용. elapsed_sec 계열은 6워커 병렬 풀에서 측정돼 환경 의존적이므로,
# 기계 독립적인 astar_calls를 계산량의 1차 근거로 볼 것.
COST_METRICS = (
    Metric("elapsed_sec", higher_is_better=False, censored_by_timeout=True),
    Metric("find_path_sec", higher_is_better=False, censored_by_timeout=True),
    Metric("astar_calls", higher_is_better=False),
    Metric("pool_cache_misses", higher_is_better=False),
)

# 2계층 원형성 대리 지표. circularity_q와의 상관 검증(이슈 H) 대상이라 같이 낸다.
PROXY_METRICS = (
    Metric("waypoint_separation_m", higher_is_better=True),
    Metric("segment_balance_ratio", higher_is_better=True),
)

ALL_METRICS = (*QUALITY_METRICS, *COST_METRICS, *PROXY_METRICS)

# 조건(= 같은 문제 인스턴스)을 식별하는 컬럼 후보. 파일마다 있는 것만 쓴다.
# algorithm과 seed는 조건이 아니라 "그 조건 위에서 무엇을 몇 번 돌렸는가"이므로 제외한다.
_CONDITION_CANDIDATES = ("scenario_id", "mode", "start_node", "target_km")

# 스윕 러너가 붙이는 노브 컬럼(alns_iterations 등)도 조건의 일부다 — 설정이 다르면
# 다른 조건이다. 다만 결과 스키마(RESULT_COLUMNS)에 이미 있는 컬럼은 제외해야 한다:
# alns_operator_stats는 이름이 패턴에 걸리지만 실행 결과로 나온 JSON 진단 문자열이라,
# 조건으로 취급하면 행마다 값이 달라 모든 조건이 1행씩으로 쪼개진다(2026-09-10 실측 CSV에서
# 실제로 발생). 조건은 "실행 전에 정해지는 것"이고 결과 컬럼은 "실행 후에 나오는 것"이다.
_KNOB_PATTERN = re.compile(r"^(alns|vns)_")
_RESULT_SCHEMA_COLUMNS = frozenset(RESULT_COLUMNS)

_RANKING_COLUMNS = ("pass_rate", "distance_deviation_km_mean", "repeated_edge_ratio_mean")
_RANKING_ASCENDING = (False, True, True)  # pass_rate만 높을수록 좋다


def _is_knob_column(column: str) -> bool:
    return bool(_KNOB_PATTERN.match(column)) and column not in _RESULT_SCHEMA_COLUMNS


def condition_columns(df: pd.DataFrame) -> list[str]:
    """이 CSV에서 조건을 식별하는 컬럼들."""
    columns = [c for c in _CONDITION_CANDIDATES if c in df.columns]
    columns += [c for c in df.columns if _is_knob_column(c)]
    return columns


def load_results(paths: list[Path]) -> pd.DataFrame:
    """여러 raw CSV를 하나로 쌓는다.

    이슈 원문은 두 CSV를 "(seed, start_node, target_km) 키로 조인"하라고 했는데, 실제
    두 파일(alns_validation / min_separation_validation)은 같은 격자를 서로 다른
    알고리즘으로 돈 결과다. 즉 컬럼을 옆으로 붙이는 join이 아니라 행을 아래로 쌓는
    concat이 맞다 — join하면 같은 조건의 서로 다른 알고리즘이 한 행에 뭉개진다.

    스키마가 다른 CSV(구 컬럼 구성으로 만들어진 파일)도 받아들이되, 없는 지표 컬럼은
    NaN으로 채우고 경고한다 — 옛 파일에는 passed/circularity_q/prune_* 등이 없다.
    """
    frames = []
    for path in paths:
        frame = pd.read_csv(path)
        frame.insert(0, "source_file", path.name)
        frames.append(frame)

    merged = pd.concat(frames, ignore_index=True, sort=False)

    missing = [m.column for m in ALL_METRICS if m.column not in merged.columns]
    if missing:
        print(f"[경고] 입력 CSV에 없는 지표 컬럼(집계에서 제외됨): {', '.join(missing)}")
    if "passed" not in merged.columns:
        print(
            "[경고] passed 컬럼이 없습니다 — 합격 게이트 이전에 만들어진 CSV입니다. "
            "pass_rate와 순위가 산출되지 않으니, 결정 근거로 쓰려면 다시 실행하세요."
        )
    return merged


def _available(metrics, df: pd.DataFrame):
    return [m for m in metrics if m.column in df.columns]


def _pass_rate(group: pd.DataFrame):
    if "passed" not in group.columns or not group["passed"].notna().any():
        return None
    return group["passed"].mean()


def _metric_sources(group: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(성공 행, 타임아웃 제외 행). 앞은 품질·계산량용, 뒤는 시간용이다."""
    return group[group["status"] == "ok"], group[group["status"] != "timeout"]


def per_condition(df: pd.DataFrame) -> pd.DataFrame:
    """(algorithm × 조건)마다 시드 반복을 접는다.

    pass_rate는 실패·타임아웃 행까지 포함한 전체에서 계산한다(실패는 곧 불합격이므로
    분모에서 빼면 안 된다). 반대로 품질·비용 통계는 성공 행에서만 낸다 — 실패 행은
    지표가 비어 있기 때문이다. 그래서 두 수치는 항상 같이 읽어야 한다.
    """
    keys = ["algorithm", *condition_columns(df)]
    metrics = _available(ALL_METRICS, df)
    rows = []

    for key_values, group in df.groupby(keys, dropna=False):
        if not isinstance(key_values, tuple):
            key_values = (key_values,)
        row = dict(zip(keys, key_values))
        row["n_runs"] = len(group)
        row["n_ok"] = int((group["status"] == "ok").sum())
        row["n_timeout"] = int((group["status"] == "timeout").sum())
        row["n_failed"] = int((group["status"] == "failed").sum())
        row["pass_rate"] = _pass_rate(group)

        ok, not_timed_out = _metric_sources(group)
        for metric in metrics:
            source = not_timed_out if metric.censored_by_timeout else ok
            values = source[metric.column].dropna()
            row[f"{metric.column}_mean"] = values.mean() if len(values) else None
            row[f"{metric.column}_std"] = values.std() if len(values) > 1 else None
            row[f"{metric.column}_worst"] = metric.worst(values) if len(values) else None

        rows.append(row)

    return pd.DataFrame(rows).sort_values(keys).reset_index(drop=True)


def per_algorithm(df: pd.DataFrame) -> pd.DataFrame:
    """알고리즘별 전체 요약. 모든 조건·시드를 한데 모은 뒤 분위수를 낸다.

    p95를 조건 단위가 아니라 여기서 내는 이유: 조건당 시드가 10개면 nearest-rank p95가
    최댓값과 같아져 worst와 구분되지 않는다(stats.percentile docstring).
    """
    metrics = _available(ALL_METRICS, df)
    rows = []

    for algorithm, group in df.groupby("algorithm", dropna=False):
        row = {"algorithm": algorithm}
        row["n_runs"] = len(group)
        row["n_ok"] = int((group["status"] == "ok").sum())
        row["n_timeout"] = int((group["status"] == "timeout").sum())
        row["pass_rate"] = _pass_rate(group)

        ok, not_timed_out = _metric_sources(group)
        for metric in metrics:
            source = not_timed_out if metric.censored_by_timeout else ok
            values = source[metric.column].dropna()
            row[f"{metric.column}_mean"] = values.mean() if len(values) else None
            row[f"{metric.column}_std"] = values.std() if len(values) > 1 else None
            row[f"{metric.column}_p95"] = metric.p95(values)
            row[f"{metric.column}_worst"] = metric.worst(values) if len(values) else None

        rows.append(row)

    return pd.DataFrame(rows).sort_values("algorithm").reset_index(drop=True)


def _condition_keys_of(condition_df: pd.DataFrame) -> list[str]:
    return [
        c for c in condition_df.columns
        if c in _CONDITION_CANDIDATES or _is_knob_column(c)
    ]


def paired_conditions(condition_df: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    """모든 알고리즘이 최소 1회 성공한 조건만 남긴다(짝지은 비교용).

    조건 난이도가 섞인 채 평균을 비교하면, 쉬운 조건만 성공한 알고리즘이 유리해진다.
    반환값은 (필터된 표, 전체 조건 수, 남은 조건 수).

    필터를 파이썬 집합 멤버십이 아니라 merge로 하는 이유(2026-09-10): 조건 키에 NaN이
    섞이면(예: 시드를 안 쓰는 solver의 seed=NaN, 노브가 비어 있는 행) `nan in {nan}`은
    같은 객체가 아닌 한 False라서 해당 조건이 조용히 전부 탈락한다. pandas merge는
    NaN 키를 정상적으로 맞춰준다.
    """
    keys = _condition_keys_of(condition_df)
    if not keys or condition_df.empty:
        return condition_df, 0, 0

    total_algorithms = condition_df["algorithm"].nunique()
    total = condition_df.groupby(keys, dropna=False).ngroups

    solved = (
        condition_df[condition_df["n_ok"] > 0]
        .groupby(keys, dropna=False)["algorithm"]
        .nunique()
        .rename("_algorithms_solved")
        .reset_index()
    )
    merged = condition_df.merge(solved, on=keys, how="left")
    paired = merged[merged["_algorithms_solved"] == total_algorithms].drop(columns="_algorithms_solved")

    kept = paired.groupby(keys, dropna=False).ngroups if not paired.empty else 0
    return paired.reset_index(drop=True), total, kept


def win_rates(condition_df: pd.DataFrame) -> pd.DataFrame:
    """조건마다 순위 규칙으로 1위를 뽑아 승률을 센다.

    주변 평균(전체 조건을 뭉갠 평균)보다 강한 비교다 — 조건 난이도가 섞여 있어도
    "같은 조건에서 누가 이겼는가"는 흔들리지 않는다.
    동점이면 공동 1위로 둘 다 승리로 센다(승률 합이 1을 넘을 수 있다).
    """
    keys = _condition_keys_of(condition_df)
    usable = [c for c in _RANKING_COLUMNS if c in condition_df.columns]
    if not keys or not usable or condition_df.empty:
        return pd.DataFrame()

    ascending = [asc for col, asc in zip(_RANKING_COLUMNS, _RANKING_ASCENDING) if col in usable]

    wins = []
    for _, group in condition_df.groupby(keys, dropna=False):
        ordered = group.sort_values(usable, ascending=ascending, na_position="last")
        if ordered.empty:
            continue
        best = ordered.iloc[0][usable]
        for _, candidate in ordered.iterrows():
            if candidate[usable].equals(best):
                wins.append(candidate["algorithm"])
            else:
                break  # 정렬돼 있으므로 첫 불일치 이후는 전부 패배

    total = condition_df.groupby(keys, dropna=False).ngroups
    if not wins:
        return pd.DataFrame()

    counts = pd.Series(wins).value_counts()
    return (
        pd.DataFrame({
            "algorithm": counts.index,
            "wins": counts.values,
            "conditions": total,
            "win_rate": (counts.values / total).round(4),
        })
        .sort_values("win_rate", ascending=False)
        .reset_index(drop=True)
    )


def budget_report(algorithm_df: pd.DataFrame) -> str:
    """알고리즘 간 탐색 예산 차이를 경고한다.

    집계로는 예산을 맞출 수 없다 — 이미 각자 다른 예산으로 실행된 결과이기 때문이다.
    여기서 할 수 있는 것은 "지금 비교가 예산 차이에 오염돼 있는지"를 드러내는 것뿐이고,
    실제 동일 예산 비교는 astar_calls를 맞춘 조건으로 다시 실행해야 얻는다.
    """
    if "astar_calls_mean" not in algorithm_df.columns:
        return "[예산] astar_calls 컬럼이 없어 예산 비교를 생략합니다."

    calls = algorithm_df.set_index("algorithm")["astar_calls_mean"].dropna()
    calls = calls[calls > 0]
    if len(calls) < 2:
        return "[예산] 비교할 알고리즘이 부족합니다."

    ratio = calls.max() / calls.min()
    lines = [
        "[예산] 알고리즘별 평균 astar_calls: "
        + ", ".join(f"{name}={value:,.0f}" for name, value in calls.sort_values().items()),
        f"[예산] 최대/최소 비율 = {ratio:.1f}배",
    ]
    if ratio > 2:
        lines.append(
            "[경고] 탐색 예산이 2배 넘게 차이납니다. 이 상태의 품질 비교는 '알고리즘이 좋은 것'이 아니라 "
            "'예산이 큰 것'을 고를 수 있습니다. 결론을 내기 전에 astar_calls를 맞춘 조건으로 "
            "재실행하세요 — 집계로는 보정할 수 없습니다."
        )
    return "\n".join(lines)


def _print_section(title: str, frame: pd.DataFrame, columns: list[str] | None = None) -> None:
    print(f"\n=== {title} ===")
    if frame.empty:
        print("(해당 없음)")
        return
    view = frame[[c for c in columns if c in frame.columns]] if columns else frame
    print(view.round(4).to_string(index=False))


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="벤치마크 raw CSV 집계기")
    parser.add_argument("inputs", nargs="+", type=Path, help="집계할 raw CSV 경로(여러 개면 행으로 쌓음)")
    parser.add_argument(
        "--out-dir", type=Path, default=Path("benchmarks/results"),
        help="집계 결과 CSV 저장 위치 (기본값: benchmarks/results)",
    )
    parser.add_argument(
        "--mode", choices=["circular", "oneway", "all"], default="circular",
        help="집계 대상 mode. 게이트가 순환 전용이라 기본값은 circular (mode 컬럼이 없으면 무시)",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    df = load_results(args.inputs)

    if "mode" in df.columns and args.mode != "all":
        before = len(df)
        df = df[df["mode"] == args.mode]
        print(f"[필터] mode={args.mode} 행만 사용: {len(df)}/{before}")
    if df.empty:
        print("[오류] 집계할 행이 없습니다.")
        return

    conditions = condition_columns(df)
    print(f"[입력] {len(df)}행, 알고리즘 {df['algorithm'].nunique()}종, 조건 컬럼: {conditions or '(없음)'}")

    censored = int((df["status"] == "timeout").sum())
    if censored:
        print(
            f"[주의] 타임아웃 {censored}행의 elapsed_sec은 제한시간에서 잘린 값이라 "
            "시간 통계에서 제외했습니다(품질 통계에서는 실패로 계산됩니다)."
        )

    condition_df = per_condition(df)
    algorithm_df = per_algorithm(df)
    paired_df, total_conditions, kept_conditions = paired_conditions(condition_df)
    wins_df = win_rates(paired_df if kept_conditions else condition_df)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    condition_df.to_csv(args.out_dir / "aggregate_by_condition.csv", index=False)
    algorithm_df.to_csv(args.out_dir / "aggregate_by_algorithm.csv", index=False)
    if not wins_df.empty:
        wins_df.to_csv(args.out_dir / "aggregate_win_rates.csv", index=False)

    _print_section(
        "알고리즘별 전체 요약 (모든 조건·시드 합산)",
        algorithm_df,
        [
            "algorithm", "n_runs", "n_ok", "n_timeout", "pass_rate",
            "distance_deviation_km_mean", "distance_deviation_km_std",
            "distance_deviation_km_p95", "distance_deviation_km_worst",
            "repeated_edge_ratio_mean", "repeated_edge_ratio_worst",
            "circularity_q_mean", "circularity_q_worst",
            "elapsed_sec_mean", "elapsed_sec_worst", "astar_calls_mean",
        ],
    )

    print(
        f"\n[짝지은 비교] 전체 {total_conditions}개 조건 중 모든 알고리즘이 성공한 "
        f"{kept_conditions}개만 사용합니다."
    )
    if kept_conditions < total_conditions:
        print(
            "  나머지 조건은 일부 알고리즘이 전부 실패해 제외됐습니다 — 그 알고리즘의 품질 평균은 "
            "쉬운 조건만 반영하므로, 위 전체 요약의 품질 수치는 pass_rate와 함께 읽으세요."
        )

    _print_section(
        f"짝지은 비교 — 알고리즘 승률 (순위 규칙: {' → '.join(_RANKING_COLUMNS)})",
        wins_df,
    )

    print()
    print(budget_report(algorithm_df))

    print(f"\n결과 저장 완료: {args.out_dir}/aggregate_by_condition.csv, aggregate_by_algorithm.csv")
    if not wins_df.empty:
        print(f"                {args.out_dir}/aggregate_win_rates.csv")


if __name__ == "__main__":
    main()
