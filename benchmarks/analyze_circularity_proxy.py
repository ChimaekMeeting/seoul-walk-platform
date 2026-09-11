"""
benchmarks/analyze_circularity_proxy.py

원형성 대리 지표 검증(2026-09-10 신규, 이슈 H). 이 벤치마크 작업의 핵심 산출물이다.

━━ 무엇을 확인하려는가 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
엔진에는 "구간 길이의 최솟값이 클수록 원형에 가깝다"는 설계 의도로 도입된
waypoint_separation_m이 있고, 전체 구간의 균형을 보는 segment_balance_ratio도 있다.
그런데 둘 다 "선언한 경유지 분해"를 기준으로 계산돼(compute_route_geometry_metrics),
정말 최종 경로의 원형성과 관계가 있는지 확인할 기준값 자체가 없었다.

circularity_q(등주 지수 4πA/P², 최종 경로 좌표만 사용)가 그 기준값이다. 이 스크립트는
두 대리 지표가 circularity_q를 실제로 예측하는지, 어느 쪽이 더 잘 예측하는지를 잰다.

━━ 결과를 읽을 때 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 상관계수는 Spearman(순위 상관)을 1차 근거로 본다. 대리 지표와 원형성의 관계가 선형일
  이유가 없고, 순위 상관은 단조 관계만 가정하므로 더 안전하다. Pearson은 참고로만 낸다.
- 표본이 작으면 상관계수 하나로 아무것도 말할 수 없다. 부트스트랩 95% 신뢰구간을 함께
  내고, 구간이 0을 포함하면 "관계 있음"이라고 말하지 않는다.
- 부트스트랩은 **행이 아니라 조건을 재표집한다**(2026-09-11). 행은 독립이 아니다 —
  같은 조건(출발지·거리)을 시드만 바꿔 여러 번 돌린 결과이고, 알고리즘별로도 군집돼
  있다. 행을 i.i.d.로 뽑으면 실제 독립 단위보다 표본이 많은 것처럼 계산돼 신뢰구간이
  실제보다 좁아지고, "0을 제외한다"는 판정이 그만큼 관대해진다.
  조건이 MIN_CLUSTERS개 미만이면 재표집할 군집 자체가 부족하므로 행 단위로 물러서되,
  그 사실을 표(재표집단위 컬럼)에 남긴다.
- 경유지가 pruning으로 사라진 행에서는 대리 지표가 최종 경로와 다른 것을 서술한다.
  보존/소실을 나눠서 낸다 — 소실 행에서만 상관이 무너진다면 그건 지표가 틀린 게 아니라
  측정 위치가 틀린 것이다.

실행:
    python -m benchmarks.analyze_circularity_proxy benchmarks/geometry_validation_results.csv
    python -m benchmarks.analyze_circularity_proxy all_scenarios_results.csv --by-algorithm
"""

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from benchmarks.aggregate_results import condition_columns, load_results
from benchmarks.stats import percentile

GROUND_TRUTH = "circularity_q"
BOOTSTRAP_SAMPLES = 2000
BOOTSTRAP_SEED = 2026  # 재현 가능한 신뢰구간
MIN_SAMPLES = 8  # 이보다 적으면 상관계수를 내지 않는다 (부트스트랩도 무의미)
MIN_CLUSTERS = 5  # 조건이 이보다 적으면 군집 재표집이 성립하지 않아 행 단위로 물러선다
CONDITION_COLUMN = "_condition"  # prepare()가 만드는 군집 라벨


@dataclass(frozen=True)
class Proxy:
    """검증 대상 대리 지표."""
    column: str
    label: str
    note: str


PROXIES = (
    Proxy(
        "separation_ratio",
        "분리도 (waypoint_separation_m / target_m)",
        "설계 의도: 구간 길이 최솟값이 클수록 원형. 단 N=2에서는 내부 구간이 하나뿐이라 "
        "'최솟값'이 아니라 단일 구간 길이이고, p1 접점 구간은 아예 보지 않는다.",
    ),
    Proxy(
        "segment_balance_ratio",
        "구간 균형비 (min/max 전체 구간)",
        "p1 접점 구간까지 포함해 전체 구간의 균등도를 본다 — '모든 구간이 고르게'라는 "
        "의도에는 분리도보다 이쪽이 가깝다.",
    ),
    Proxy(
        "waypoint_angle_diff_deg",
        "경유지 방위각차 (도)",
        "구간 균등만으로는 원형이 보장되지 않는다. 방위각이 고르게 퍼져야 정다각형에 "
        "가까워지므로 함께 잰다.",
    ),
)


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """상관 분석에 쓸 성공 행만 남기고 파생 컬럼을 만든다."""
    missing = [c for c in (GROUND_TRUTH, "status") if c not in df.columns]
    if missing:
        raise SystemExit(
            f"[오류] 필수 컬럼이 없습니다: {missing}. circularity_q는 2026-09-10 이후 CSV에만 "
            "있습니다 — 격자를 다시 실행하세요."
        )

    work = df[df["status"] == "ok"].copy()

    if {"waypoint_separation_m", "target_km"} <= set(work.columns):
        target_m = work["target_km"] * 1000
        work["separation_ratio"] = work["waypoint_separation_m"] / target_m.where(target_m > 0)

    if {"num_waypoints_used", "effective_waypoints_used"} <= set(work.columns):
        # 선언한 경유지를 전부 지났는가. False면 기하 지표가 최종 경로와 다른 것을 서술한다.
        work["waypoints_preserved"] = (
            work["num_waypoints_used"] == work["effective_waypoints_used"]
        )
    else:
        work["waypoints_preserved"] = pd.NA

    # 부트스트랩의 재표집 단위. 같은 조건을 시드만 바꿔 돌린 행들이 한 군집이 된다.
    keys = condition_columns(work)
    work[CONDITION_COLUMN] = (
        work[keys].astype(str).agg("|".join, axis=1) if keys else "(단일 조건)"
    )

    return work


def _paired(x: pd.Series, y: pd.Series) -> pd.DataFrame:
    return pd.concat([x, y], axis=1).dropna()


def _corr(x: pd.Series, y: pd.Series, method: str) -> float | None:
    """상관계수. 표본이 MIN_SAMPLES 미만이면 내지 않는다 — 우연한 큰 값이 결론으로
    둔갑하는 것을 막기 위함이다.

    Spearman을 직접 계산하는 이유: pandas의 `corr(method="spearman")`은 내부적으로
    scipy.stats.spearmanr를 import하는데 이 저장소에는 scipy가 없다. Spearman은 정의상
    "순위로 바꾼 뒤의 Pearson"이고 Series.rank()가 동점을 평균 순위로 처리하므로,
    순위 변환 후 기본 corr(pearson)을 쓰면 표준 Spearman과 같은 값이 나온다.
    """
    pair = _paired(x, y)
    if len(pair) < MIN_SAMPLES:
        return None

    a, b = pair.iloc[:, 0], pair.iloc[:, 1]
    if method == "spearman":
        a, b = a.rank(), b.rank()
    value = a.corr(b)  # 기본값 pearson — scipy 불필요
    return None if pd.isna(value) else value


def _rank_rows(values: np.ndarray) -> np.ndarray:
    """행마다 순위를 매긴다(동점은 임의 순서).

    부트스트랩 구간 추정용 근사다 — 점추정치는 pandas의 동점 평균 순위를 쓰므로 동점이
    많은 지표(예: spike_count)에서 구간과 점추정치가 미세하게 어긋날 수 있다. 구간의
    용도가 "0을 포함하는가"의 판단이라 이 정도 근사는 결론을 바꾸지 않는다.
    """
    order = values.argsort(axis=1)
    ranks = np.empty(order.shape, dtype=float)
    rows = np.arange(values.shape[0])[:, None]
    ranks[rows, order] = np.arange(1, values.shape[1] + 1)
    return ranks


def _pearson_rows(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a = a - a.mean(axis=1, keepdims=True)
    b = b - b.mean(axis=1, keepdims=True)
    numerator = (a * b).sum(axis=1)
    denominator = np.sqrt((a ** 2).sum(axis=1) * (b ** 2).sum(axis=1))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(denominator > 0, numerator / denominator, np.nan)


def _spearman_of(xs: np.ndarray, ys: np.ndarray) -> float:
    """1차원 배열 두 개의 Spearman. 군집 재표집은 표본 길이가 매 회 달라져 행렬로
    한 번에 처리할 수 없으므로 이 단건 경로를 쓴다."""
    if len(xs) < 2:
        return float("nan")
    return float(_pearson_rows(_rank_rows(xs[None, :]), _rank_rows(ys[None, :]))[0])


def bootstrap_ci(
    x: pd.Series, y: pd.Series, clusters: pd.Series | None = None,
    samples: int = BOOTSTRAP_SAMPLES,
) -> tuple:
    """Spearman 상관의 부트스트랩 95% 신뢰구간.

    scipy가 없어 해석적 p-value를 낼 수 없고, 애초에 표본이 작을 때는 재표집 구간이
    점추정치보다 훨씬 정직하다. 구간이 0을 포함하면 "관계가 있다"고 말하지 않는다.

    clusters를 주면 **행이 아니라 군집을 재표집한다**(2026-09-11). 행은 독립이 아니다 —
    같은 조건을 시드만 바꿔 돌린 결과라, 행을 i.i.d.로 뽑으면 실제 독립 단위보다 표본이
    많은 것처럼 계산돼 구간이 실제보다 좁아진다. 군집이 MIN_CLUSTERS개 미만이면 재표집할
    것이 부족하므로 행 단위로 물러선다(반환값에는 드러나지 않으므로 resampling_unit()로
    확인할 것).

    반환: (하한, 상한). 표본이 부족하거나 재표집 대부분에서 상관이 정의되지 않으면
    (None, None).
    """
    pair = _paired(x, y)
    if len(pair) < MIN_SAMPLES:
        return (None, None)

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    xs = pair.iloc[:, 0].to_numpy(dtype=float)
    ys = pair.iloc[:, 1].to_numpy(dtype=float)

    groups = _cluster_groups(pair, clusters)
    if groups is None:
        index = rng.integers(0, len(pair), (samples, len(pair)))
        estimates = _pearson_rows(_rank_rows(xs[index]), _rank_rows(ys[index]))
    else:
        drawn = rng.integers(0, len(groups), (samples, len(groups)))
        estimates = np.empty(samples, dtype=float)
        for i, picks in enumerate(drawn):
            rows = np.concatenate([groups[p] for p in picks])
            estimates[i] = _spearman_of(xs[rows], ys[rows])

    estimates = estimates[~np.isnan(estimates)]
    if len(estimates) < samples // 2:
        return (None, None)  # 재표집 대부분이 상수라 상관이 정의되지 않음

    values = estimates.tolist()
    return (percentile(values, 0.025), percentile(values, 0.975))


def _cluster_groups(pair: pd.DataFrame, clusters: pd.Series | None):
    """재표집할 군집별 행 위치 목록. 군집이 부족하면 None(행 단위로 물러섬)."""
    if clusters is None:
        return None
    aligned = clusters.reindex(pair.index)
    if aligned.isna().any() or aligned.nunique() < MIN_CLUSTERS:
        return None
    positions = pd.Series(np.arange(len(pair)), index=pair.index)
    return [group.to_numpy() for _, group in positions.groupby(aligned.to_numpy())]


def resampling_unit(pair_length: int, clusters: pd.Series | None, index=None) -> str:
    """이 표본에 실제로 쓰인 재표집 단위 이름 — 표에 그대로 싣는다."""
    if clusters is None or index is None:
        return "행"
    aligned = clusters.reindex(index)
    distinct = aligned.nunique()
    if aligned.isna().any() or distinct < MIN_CLUSTERS:
        return f"행(군집 {distinct}개 < {MIN_CLUSTERS})"
    return f"조건 {distinct}개"


def correlation_row(label: str, x: pd.Series, y: pd.Series,
                    clusters: pd.Series | None = None) -> dict:
    pair = _paired(x, y)
    low, high = bootstrap_ci(x, y, clusters)
    excludes_zero = (
        "예" if low is not None and high is not None and (low > 0) == (high > 0) else "아니오"
    )
    return {
        "구분": label,
        "n": len(pair),
        "재표집단위": resampling_unit(len(pair), clusters, pair.index),
        "spearman": _corr(x, y, "spearman"),
        "95%CI_low": low,
        "95%CI_high": high,
        "0_제외": excludes_zero,
        "pearson": _corr(x, y, "pearson"),
    }


def correlations(work: pd.DataFrame, proxies=PROXIES) -> pd.DataFrame:
    """대리 지표별 상관표. 경유지 보존 여부로 나눠서 함께 낸다.

    신뢰구간은 조건 단위로 재표집한다 — 행은 독립이 아니다(bootstrap_ci docstring 참고).
    """
    clusters = work[CONDITION_COLUMN] if CONDITION_COLUMN in work.columns else None
    rows = []
    for proxy in proxies:
        if proxy.column not in work.columns:
            continue
        truth = work[GROUND_TRUTH]
        rows.append({
            "지표": proxy.label,
            **correlation_row("전체", work[proxy.column], truth, clusters),
        })

        if work["waypoints_preserved"].notna().any():
            for preserved, subset in work.groupby("waypoints_preserved", dropna=True):
                label = "경유지 보존" if preserved else "경유지 소실"
                rows.append({
                    "지표": proxy.label,
                    **correlation_row(label, subset[proxy.column], subset[GROUND_TRUTH], clusters),
                })

    return pd.DataFrame(rows)


def correlations_by_n(work: pd.DataFrame, proxies=PROXIES) -> pd.DataFrame:
    """경유지 개수 N별 상관. N=2에서는 분리도가 단일 구간이라 '최솟값' 성질이 없다."""
    if "num_waypoints_used" not in work.columns:
        return pd.DataFrame()

    clusters = work[CONDITION_COLUMN] if CONDITION_COLUMN in work.columns else None
    rows = []
    for n, subset in work.groupby("num_waypoints_used", dropna=True):
        for proxy in proxies:
            if proxy.column not in subset.columns:
                continue
            rows.append({
                "N": int(n), "지표": proxy.label,
                **correlation_row(
                    f"N={int(n)}", subset[proxy.column], subset[GROUND_TRUTH], clusters
                ),
            })
    return pd.DataFrame(rows)


def waypoint_loss_report(work: pd.DataFrame) -> pd.DataFrame:
    """N별 경유지 소실 현황 — N을 올리는 것이 실제로 값을 하는지의 근거.

    N을 늘려도 effective가 따라 늘지 않으면, 늘린 만큼의 A* 호출이 낭비다.
    경유지는 내부 수단이므로 소실 자체가 품질 미달은 아니지만, 비용은 실제로 나간다.
    """
    if "num_waypoints_used" not in work.columns:
        return pd.DataFrame()

    aggregations = {
        "n": ("num_waypoints_used", "size"),
        "선언N": ("num_waypoints_used", "mean"),
        "실제통과_평균": ("effective_waypoints_used", "mean"),
        "보존율": ("waypoints_preserved", "mean"),
        "원형성_평균": (GROUND_TRUTH, "mean"),
    }
    for column, name in (
        ("astar_calls", "astar호출_평균"),
        ("waypoints_lost_clean", "소실_clean"),
        ("waypoints_lost_repeated", "소실_repeated"),
        ("prune_branch_length_m", "잘라낸길이_평균"),
    ):
        if column in work.columns:
            aggregations[name] = (column, "mean")

    return (
        work.groupby("num_waypoints_used", dropna=True)
        .agg(**aggregations)
        .round(4)
        .reset_index(drop=True)
    )


def prune_criterion_report(work: pd.DataFrame) -> str:
    """겹침 제거 기준을 바꿀 가치가 있는지의 근거.

    waypoints_lost_clean(재통행 없는 가지에 휩쓸려 사라진 경유지)이 지배적이면 기준을
    길이에서 겹침으로 바꾸는 것만으로 소실이 줄어든다. lost_repeated가 지배적이면
    기준을 바꿔도 그대로다(PruneDiagnostics 클래스 docstring).
    """
    if not {"waypoints_lost_clean", "waypoints_lost_repeated"} <= set(work.columns):
        return "[겹침 제거 기준] prune 진단 컬럼이 없어 판단을 생략합니다."

    clean = work["waypoints_lost_clean"].fillna(0).sum()
    repeated = work["waypoints_lost_repeated"].fillna(0).sum()
    total = clean + repeated
    if total == 0:
        return "[겹침 제거 기준] 경유지 소실이 한 건도 없습니다 — 기준 전환의 실익이 없습니다."

    share = clean / total
    verdict_text = (
        "겹침 기준으로 바꾸면 소실 대부분이 사라집니다 — 전환을 검토할 근거가 있습니다."
        if share >= 0.5 else
        "기준을 바꿔도 소실 대부분이 남습니다 — 전환의 실익이 작습니다."
    )
    return (
        f"[겹침 제거 기준] 사라진 경유지 {int(total)}개 중 "
        f"clean {int(clean)}개({share:.0%}) / repeated {int(repeated)}개({1 - share:.0%}). "
        f"{verdict_text}"
    )


def verdict(correlation_df: pd.DataFrame) -> str:
    """어느 대리 지표가 원형성을 더 잘 예측하는지의 결론."""
    if correlation_df.empty:
        return "[결론] 분석할 대리 지표 컬럼이 없습니다."

    overall = correlation_df[correlation_df["구분"] == "전체"].dropna(subset=["spearman"])
    if overall.empty:
        return (
            "[결론] 표본이 부족해 상관을 낼 수 없습니다. 조건·시드를 늘려 다시 실행하세요 "
            f"(지표당 최소 {MIN_SAMPLES}개 필요)."
        )

    significant = overall[overall["0_제외"] == "예"]
    if significant.empty:
        return (
            "[결론] 어떤 대리 지표도 신뢰구간이 0을 제외하지 못했습니다. 현재 데이터로는 "
            "'구간 최솟값이 클수록 원형'이라는 가정을 뒷받침할 수도, 반박할 수도 없습니다. "
            "표본을 늘리기 전에는 분리도를 목적함수로 승격하지 마세요."
        )

    best = significant.loc[significant["spearman"].abs().idxmax()]
    return (
        f"[결론] 원형성을 가장 잘 예측하는 대리 지표: {best['지표']} "
        f"(Spearman {best['spearman']:.3f}, 95%CI [{best['95%CI_low']:.3f}, {best['95%CI_high']:.3f}], "
        f"n={int(best['n'])}).\n"
        "        이 결과를 분리도의 목적함수 승격 판단(이슈 I)에 그대로 넘기세요."
    )


def _print(title: str, frame: pd.DataFrame) -> None:
    print(f"\n=== {title} ===")
    if frame is None or frame.empty:
        print("(해당 없음 — 필요한 컬럼이나 표본이 없습니다)")
        return
    print(frame.round(4).to_string(index=False))


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="원형성 대리 지표 검증(이슈 H)")
    parser.add_argument("inputs", nargs="+", type=Path, help="raw CSV 경로")
    parser.add_argument(
        "--out-dir", type=Path, default=Path("benchmarks/results"),
        help="분석 결과 CSV 저장 위치",
    )
    parser.add_argument(
        "--by-algorithm", action="store_true",
        help="알고리즘별로도 상관을 낸다(표본이 알고리즘 수만큼 쪼개지므로 데이터가 많을 때만)",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    work = prepare(load_results(args.inputs))
    print(f"[입력] 성공 행 {len(work)}개, 알고리즘 {work['algorithm'].nunique()}종")

    if work["waypoints_preserved"].notna().any():
        preserved_rate = work["waypoints_preserved"].mean()
        print(f"[경유지] 선언한 경유지를 전부 지난 행 비율: {preserved_rate:.1%}")
        if preserved_rate < 1.0:
            print(
                "  소실 행에서는 분리도·균형비가 최종 경로가 아닌 '선언 분해'를 서술합니다 — "
                "아래 표에서 보존/소실을 나눠 보세요."
            )

    for proxy in PROXIES:
        if proxy.column in work.columns:
            print(f"\n  · {proxy.label}\n    {proxy.note}")

    correlation_df = correlations(work)
    _print(f"대리 지표 ↔ {GROUND_TRUTH} 상관", correlation_df)
    _print("경유지 개수 N별 상관", correlations_by_n(work))
    _print("N별 경유지 소실 현황", waypoint_loss_report(work))

    if args.by_algorithm:
        frames = []
        for algorithm, subset in work.groupby("algorithm"):
            per_algorithm = correlations(subset)
            if per_algorithm.empty:
                continue
            per_algorithm.insert(0, "algorithm", algorithm)
            frames.append(per_algorithm[per_algorithm["구분"] == "전체"])
        _print(
            "알고리즘별 상관(전체 행 기준)",
            pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(),
        )

    print()
    print(prune_criterion_report(work))
    print()
    print(verdict(correlation_df))

    if "num_waypoints_used" in work.columns and work["num_waypoints_used"].nunique() < 2:
        print(
            "\n[주의] num_waypoints가 한 값뿐이라 N 스윕 분석이 성립하지 않습니다. "
            "--num-waypoints 2~6으로 나눠 실행한 CSV를 함께 넣으세요."
        )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    correlation_df.to_csv(args.out_dir / "circularity_proxy_correlation.csv", index=False)
    print(f"\n결과 저장 완료: {args.out_dir}/circularity_proxy_correlation.csv")


if __name__ == "__main__":
    main()
