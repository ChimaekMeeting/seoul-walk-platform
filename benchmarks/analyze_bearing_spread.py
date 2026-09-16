"""
benchmarks/analyze_bearing_spread.py

waypoint_bearings_deg(2026-09-16 추가 컬럼)로 "전역 배치 실패"를 집계한다.
이슈 "구축 단계 원형성 지향 항 추가" 1단계 게이트의 판정 본체다.

━━ 무엇을 판정하는가 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
현재 각도 다양성 항(angle_diversity_weight_m·|cos|)은 p1 기준으로 "직전 경유지와의
상대각"만 본다. 그래서 w1→w2가 +90도, w2→w3가 -90도인 배치는 각 단계 페널티가 모두 0인데
w3가 w1과 같은 방위로 돌아온다. 이 스크립트는 그 되돌아옴이 실제 경로에서 나오는지 센다.

지표:
    turn_k         = wrap180(bearing_{k+1} - bearing_k)   부호 있는 회전량
    sign_reversals = turn의 부호가 뒤집힌 횟수. 1회 이상이면 전역 배치 실패다.
    span_deg       = 방위각 전체를 담는 최소 호
    ideal_span_deg = (N-1)*180/(N+1)
        p1을 지나는 원 위에 N+1개 점을 균등 배치하면, p1에서 본 경유지 방위각은 원주각
        성질상 180/(N+1)도씩 벌어진다. 따라서 전체 폭은 (N-1)*180/(N+1)이고 360도가
        아니다(N=4에서 108도). 이 값을 1로 두고 span_ratio를 읽는다.

판정: sign_reversals > 0인 행의 비율이 무시할 수준이면 이 이슈의 전제가 관측되지 않은
것이므로 구현(2단계)으로 넘어가지 않는다.

실행:
    poetry run python -m benchmarks.analyze_bearing_spread benchmarks/circularity_prior_probe_results.csv
"""

import argparse
import json
import math
from pathlib import Path

import pandas as pd

from benchmarks.measure_pool_geometry import circular_span_deg

BEARING_COLUMN = "waypoint_bearings_deg"


def parse_bearings(raw):
    """JSON 문자열 컬럼을 방위각 목록으로 되돌린다. 값이 없거나 깨졌으면 None.

    경유지가 1개뿐이면 인접 차이 자체가 없어 전역 배치가 정의되지 않으므로 None으로 본다.
    """
    if not isinstance(raw, str) or not raw:
        return None
    try:
        values = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(values, list) or len(values) < 2:
        return None
    try:
        return [float(v) % 360.0 for v in values]
    except (TypeError, ValueError):
        return None


def signed_turns_deg(bearings):
    """인접 방위각의 부호 있는 차이를 (-180, 180]으로 접어 반환한다."""
    return [
        (bearings[i + 1] - bearings[i] + 180.0) % 360.0 - 180.0
        for i in range(len(bearings) - 1)
    ]


def sign_reversals(turns) -> int:
    """부호가 뒤집힌 횟수.

    0도(정확히 같은 방위)는 직전 부호를 잇는 것으로 본다 — 방향을 바꾸지 않았으므로
    되돌아옴으로 세지 않는다.
    """
    reversals, previous = 0, 0
    for turn in turns:
        current = (turn > 0) - (turn < 0)
        if current == 0:
            continue
        if previous != 0 and current != previous:
            reversals += 1
        previous = current
    return reversals


def ideal_span_deg(n: int) -> float:
    """원 위 균등 배치에서 p1이 보는 경유지 방위각의 전체 폭(도)."""
    return (n - 1) * 180.0 / (n + 1)


def describe(bearings) -> dict:
    turns = signed_turns_deg(bearings)
    n = len(bearings)
    ideal = ideal_span_deg(n)
    span = circular_span_deg(bearings)
    return {
        "n_waypoints": n,
        "sign_reversals": sign_reversals(turns),
        "min_abs_turn_deg": min(abs(t) for t in turns),
        "span_deg": span,
        "ideal_span_deg": ideal,
        "span_ratio": (span / ideal) if ideal > 0 else math.nan,
    }


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="방위각 전역 배치 집계")
    parser.add_argument("csv", type=Path, help="결과 CSV 경로")
    args = parser.parse_args(argv)

    df = pd.read_csv(args.csv)
    df = df.loc[:, ~df.columns.duplicated()]
    if BEARING_COLUMN not in df.columns:
        raise SystemExit(
            f"[오류] {BEARING_COLUMN} 컬럼이 없습니다. 이 컬럼은 2026-09-16 이후 CSV에만 "
            "있습니다 — 격자를 다시 실행하세요."
        )

    work = df[df["status"] == "ok"].copy()
    parsed = work[BEARING_COLUMN].map(parse_bearings)
    work = work[parsed.notna()].copy()
    if work.empty:
        raise SystemExit(
            "[오류] 방위각을 읽을 수 있는 성공 행이 없습니다. 경유지가 2개 미만이면 전역 "
            "배치 실패는 정의되지 않습니다 — num_waypoints>=3으로 실행했는지 확인하세요."
        )

    metrics = pd.DataFrame(
        [describe(b) for b in parsed[parsed.notna()]], index=work.index,
    )
    work = pd.concat([work, metrics], axis=1)
    work["failed_layout"] = work["sign_reversals"] > 0

    keys = [k for k in ("algorithm", "target_km") if k in work.columns]
    summary = work.groupby(keys).agg(
        n=("failed_layout", "size"),
        실패율=("failed_layout", "mean"),
        평균뒤집힘=("sign_reversals", "mean"),
        span비중앙값=("span_ratio", "median"),
        최소회전각중앙값=("min_abs_turn_deg", "median"),
    ).round(3)

    print(f"\n대상: {args.csv} (성공·방위각 보유 {len(work)}행)")
    print(summary.to_string())
    print(f"\n전체 실패율(부호 뒤집힘 1회 이상): {work['failed_layout'].mean():.3f}")
    print(
        "판정 기준: 이 값이 무시할 수준이면 |cos| 항의 전역 배치 구멍이 실제로는 나타나지 "
        "않는 것이므로 2단계로 넘어가지 않는다."
    )


if __name__ == "__main__":
    main()
