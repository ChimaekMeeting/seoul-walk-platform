"""
benchmarks/analyze_thresholds.py

미확정 임계값들의 확정 근거를 실측에서 뽑는다(2026-09-10 신규, 이슈 I).

대상:
    1) _DEGENERATE_REPEATED_EDGE_RATIO (현재 0.35, grasp_waypoint_common.py)
       상수 주석이 "지표 정의 전환을 반영한 1차 재조정값이며, 실제 그래프 변경 전/후
       벤치마크 회귀 확인은 아직 하지 않았다"고 명시한 상태다.
    2) 합격 게이트 임계값 (benchmarks/config.py의 MAX_* 3종)
       전부 "1차 실험값"으로 들어가 있다.
    3) min_waypoint_separation_ratio (현재 0.20, GraspConfig)
       구축 단계 하드 필터다.

━━ 이 스크립트가 답할 수 없는 것 (중요) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
min_waypoint_separation_ratio가 "좋은 경로까지 걸러내고 있는가"는 **여기서 답할 수 없다**.
필터는 구축 단계에서 후보를 이미 제거하므로, 결과 CSV에는 살아남은 것만 있고 걸러진
후보의 품질은 어디에도 기록되지 않는다. 알 수 있는 것은 "통과한 것들 사이의 분포"와
"fallback으로 떨어진 행의 품질"뿐이다.

진짜 답을 얻으려면 비율을 바꿔가며 재실행해야 하는데, 현재 그 주입 경로가 없다:
min_waypoint_separation_ratio와 angle_diversity_weight_m은 GraspConfig 필드이고,
WaypointEngine 생성자는 num_waypoints만 덮어쓴다(config= 인자는 Beam 쪽만 쓴다).
정제 노브(--alns-*/--vns-*)는 refinement_options 경로라 여기에 닿지 않는다.
=> GraspConfig 주입 경로를 열어야 한다. 이 스크립트는 그 필요성을 수치로 보여줄 뿐이다.

같은 이유로 angle_diversity_weight_m(기본 1500.0)과의 상호작용도 분석만으로는 알 수 없다.

실행:
    python -m benchmarks.analyze_thresholds benchmarks/geometry_validation_results.csv
"""

import argparse
from pathlib import Path

import pandas as pd

from benchmarks.aggregate_results import load_results
from benchmarks.config import (
    MAX_DISTANCE_DEVIATION_KM,
    MAX_REPEATED_EDGE_RATIO,
    MAX_SPIKE_COUNT,
)

DEGENERATE_CANDIDATES = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50]
GATE_QUANTILES = [0.50, 0.75, 0.90, 0.95, 0.99, 1.00]
_CURRENT_MIN_SEPARATION_RATIO = 0.20  # GraspConfig.min_waypoint_separation_ratio 기본값


def successful(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["status"] == "ok"].copy()


def degenerate_threshold_sweep(work: pd.DataFrame) -> pd.DataFrame:
    """재통행 임계값 후보별로 "무엇을 걸러내고 그것이 실제로 나쁜가"를 낸다.

    좋은 임계값은 원형성이 낮은 경로를 골라내면서 멀쩡한 경로를 과도하게 잡지 않는다.
    원형성차이(비플래그 평균 − 플래그 평균)가 클수록 그 임계값이 실제로 나쁜 것을
    구분해내고 있다는 뜻이다.

    주의: is_degenerate_loop는 세 조건의 OR이고 이 임계값은 그중 하나만 바꾼다.
    나머지 둘(waypoint_separation_m, segment_balance_ratio)은 경유지 분해 기반이라
    별개로 다뤄야 한다.
    """
    if "repeated_edge_ratio" not in work.columns:
        return pd.DataFrame()

    truth = "circularity_q" if "circularity_q" in work.columns else None
    rows = []
    for threshold in DEGENERATE_CANDIDATES:
        flagged = work["repeated_edge_ratio"] > threshold
        row = {
            "임계값": threshold,
            "현재값": "←" if threshold == MAX_REPEATED_EDGE_RATIO else "",
            "플래그_건수": int(flagged.sum()),
            "플래그_비율": round(flagged.mean(), 4) if len(work) else None,
        }
        if truth:
            flagged_mean = work.loc[flagged, truth].mean()
            clean_mean = work.loc[~flagged, truth].mean()
            row["원형성_플래그"] = flagged_mean
            row["원형성_비플래그"] = clean_mean
            row["원형성차이"] = (
                clean_mean - flagged_mean
                if pd.notna(flagged_mean) and pd.notna(clean_mean) else None
            )
        rows.append(row)
    return pd.DataFrame(rows)


def gate_threshold_quantiles(work: pd.DataFrame) -> pd.DataFrame:
    """게이트 지표의 분위수 — 임계값을 어디에 두면 몇 %가 통과하는지의 근거."""
    targets = {
        "distance_deviation_km": MAX_DISTANCE_DEVIATION_KM,
        "repeated_edge_ratio": MAX_REPEATED_EDGE_RATIO,
        "spike_count": MAX_SPIKE_COUNT,
    }
    rows = []
    for column, current in targets.items():
        if column not in work.columns:
            continue
        values = work[column].dropna()
        if values.empty:
            continue
        row = {"지표": column, "현재_임계값": current, "n": len(values)}
        for quantile in GATE_QUANTILES:
            row[f"q{int(quantile * 100)}"] = values.quantile(quantile)
        row["현재값_통과율"] = round((values <= current).mean(), 4)
        rows.append(row)
    return pd.DataFrame(rows)


def separation_distribution(work: pd.DataFrame) -> pd.DataFrame:
    """분리도(waypoint_separation_m / target_m) 분포.

    필터가 target_m * 0.20 미만 후보를 구축 단계에서 제거하므로, 여기 보이는 값은 전부
    0.20 이상이어야 정상이다. 0.20 근처에 몰려 있다면 필터가 실제로 구속력을 갖고
    있다는 뜻이고, 훨씬 위쪽에 분포한다면 필터가 사실상 놀고 있다는 뜻이다.
    """
    if not {"waypoint_separation_m", "target_km"} <= set(work.columns):
        return pd.DataFrame()

    target_m = work["target_km"] * 1000
    ratio = (work["waypoint_separation_m"] / target_m.where(target_m > 0)).dropna()
    if ratio.empty:
        return pd.DataFrame()

    return pd.DataFrame([{
        "n": len(ratio),
        "현재_문턱": _CURRENT_MIN_SEPARATION_RATIO,
        "최소": ratio.min(),
        "q10": ratio.quantile(0.10),
        "q25": ratio.quantile(0.25),
        "중앙값": ratio.quantile(0.50),
        "q75": ratio.quantile(0.75),
        "최대": ratio.max(),
        "문턱_근처_비율(<0.25)": round((ratio < 0.25).mean(), 4),
    }])


def fallback_quality(work: pd.DataFrame) -> pd.DataFrame:
    """selection_status별 품질 비교.

    fallback은 "최소거리 조건을 만족하는 경유지 조합으로는 목표 거리를 못 맞췄다"는
    뜻이다. fallback 행의 품질이 feasible과 비슷하다면, 그 제약이 품질을 지켜주는 게
    아니라 그저 탐색을 좁히고 있을 가능성이 있다 — 제약 완화를 검토할 근거가 된다.
    """
    if "selection_status" not in work.columns:
        return pd.DataFrame()

    aggregations = {"n": ("selection_status", "size")}
    for column, name in (
        ("distance_deviation_km", "거리편차_평균"),
        ("repeated_edge_ratio", "재통행_평균"),
        ("circularity_q", "원형성_평균"),
        ("passed", "게이트통과율"),
    ):
        if column in work.columns:
            aggregations[name] = (column, "mean")

    return (
        work.groupby("selection_status", dropna=False)
        .agg(**aggregations)
        .round(4)
        .reset_index()
    )


def recommend_degenerate_threshold(sweep: pd.DataFrame) -> str:
    """원형성 구분력이 가장 큰 임계값을 제안한다(제안일 뿐 확정이 아니다)."""
    if sweep.empty or "원형성차이" not in sweep.columns:
        return "[제안] circularity_q가 없어 재통행 임계값을 제안할 수 없습니다."

    usable = sweep.dropna(subset=["원형성차이"])
    usable = usable[usable["플래그_건수"] > 0]
    if usable.empty:
        return (
            "[제안] 어떤 후보 임계값도 플래그되는 행을 만들지 못했습니다 — 현재 데이터에는 "
            "재통행이 심한 경로가 없습니다. 퇴화 사례가 포함된 조건으로 다시 실행하세요."
        )

    best = usable.loc[usable["원형성차이"].idxmax()]
    same = "동일합니다" if best["임계값"] == MAX_REPEATED_EDGE_RATIO else "다릅니다"
    return (
        f"[제안] 원형성 구분력이 가장 큰 재통행 임계값: {best['임계값']:.2f} "
        f"(원형성차이 {best['원형성차이']:.3f}, 플래그 {int(best['플래그_건수'])}건 / "
        f"{best['플래그_비율']:.1%}).\n"
        f"        현재 값 {MAX_REPEATED_EDGE_RATIO}와 {same}. 확정하려면 퇴화 사례가 충분히 "
        "포함된 격자에서 재확인하세요."
    )


def _print(title: str, frame: pd.DataFrame) -> None:
    print(f"\n=== {title} ===")
    if frame is None or frame.empty:
        print("(해당 없음 — 필요한 컬럼이나 표본이 없습니다)")
        return
    print(frame.round(4).to_string(index=False))


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="임계값 확정 근거 분석(이슈 I)")
    parser.add_argument("inputs", nargs="+", type=Path, help="raw CSV 경로")
    parser.add_argument("--out-dir", type=Path, default=Path("benchmarks/results"))
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    work = successful(load_results(args.inputs))
    print(f"[입력] 성공 행 {len(work)}개")

    sweep = degenerate_threshold_sweep(work)
    _print("재통행 임계값 후보 스윕 (_DEGENERATE_REPEATED_EDGE_RATIO)", sweep)
    _print("합격 게이트 지표 분위수", gate_threshold_quantiles(work))
    _print("분리도 분포 (waypoint_separation_m / target_m)", separation_distribution(work))
    _print("selection_status별 품질", fallback_quality(work))

    print()
    print(recommend_degenerate_threshold(sweep))

    print(
        "\n[한계] min_waypoint_separation_ratio(0.20)가 좋은 경로까지 걸러내는지는 이 데이터로 "
        "판단할 수 없습니다. 필터가 구축 단계에서 후보를 이미 제거해, 걸러진 후보의 품질이 "
        "CSV에 남지 않기 때문입니다."
        "\n       비율을 바꿔가며 재실행해야 하는데 현재 주입 경로가 없습니다 — "
        "min_waypoint_separation_ratio와 angle_diversity_weight_m은 GraspConfig 필드이고, "
        "WaypointEngine 생성자는 num_waypoints만 덮어씁니다. GraspConfig 주입 경로를 여는 "
        "후속 작업이 필요합니다."
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    if not sweep.empty:
        sweep.to_csv(args.out_dir / "threshold_degenerate_sweep.csv", index=False)
        print(f"\n결과 저장 완료: {args.out_dir}/threshold_degenerate_sweep.csv")


if __name__ == "__main__":
    main()
