"""
benchmarks/check_results.py

결과 CSV의 완전성을 검사한다(2026-09-10 신규, 이슈 K).

만든 이유: 이 저장소에서 반복된 실패 유형이 "컬럼을 추가했는데 러너 일부가 그 키를 안
채워 CSV에 열은 생기고 전 행이 NaN"이었다. 실제로 num_waypoints_used /
effective_waypoints_used / pool_cache_hits / pool_cache_misses 네 컬럼이 러너 4종
전부에서 비어 있었고, 아무도 눈치채지 못한 채 그 CSV로 판단이 이뤄질 뻔했다.
비어 있는 열은 조용해서 위험하다 — 자동으로 잡는다.

검사 항목:
    1) RESULT_COLUMNS가 전부 있는가(스키마 누락)
    2) 성공 행에서 반드시 채워져야 할 컬럼이 비어 있지 않은가
    3) 경유지 solver가 채워야 할 컬럼이 그 solver 행에서 비어 있지 않은가
    4) (정보) 전 행이 비어 있는 컬럼 — 그 값을 채울 solver가 격자에 없었을 수도 있으므로
       실패로 보지 않고 "누가 채웠어야 하는지"와 함께 보고만 한다

종료 코드: 위반이 있으면 1, 없으면 0 — CI에 그대로 걸 수 있다.

실행:
    python -m benchmarks.check_results benchmarks/geometry_validation_results.csv
    python -m benchmarks.check_results all_scenarios_results.csv --show-coverage
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

from benchmarks.results import RESULT_COLUMNS

# 성공(status == "ok") 행이라면 solver 종류와 무관하게 반드시 채워지는 컬럼.
# graph 없이 돌린 경우(dummy solver 등) distance 계열은 비므로 여기 넣지 않는다.
ALWAYS_REQUIRED = ("algorithm", "status", "elapsed_sec", "cost")

# 경유지 solver(이름에 "Waypoint" 포함)의 성공 행에서 반드시 채워지는 컬럼.
# 정확히 이 목록이 예전에 러너 4종에서 통째로 비어 있던 부분이다.
WAYPOINT_SOLVER_REQUIRED = (
    "num_waypoints_used", "effective_waypoints_used",
    "selection_status", "feasible", "repeated_edge_ratio",
)

# GRASP 경유지 풀을 쓰는 solver만 채우는 컬럼(Beam-Waypoint는 자체 풀이라 채우지 않는다).
GRASP_POOL_REQUIRED = ("pool_cache_hits", "pool_cache_misses")

# 전 행이 비었을 때 "누가 채웠어야 하는가"를 알려주기 위한 설명.
EMPTY_COLUMN_OWNERS = {
    "overlap_ratio": "편도(oneway) solver — 순환 전용 격자라면 비는 것이 정상",
    "alns_operator_stats": "ALNS 정제 solver(*-wp-alns)",
    "find_path_sec": "이 지표를 보고하는 solver가 아직 없음",
    "pool_cache_hits": "GRASP 경유지 풀 solver(grasp-wp-*)",
    "pool_cache_misses": "GRASP 경유지 풀 solver(grasp-wp-*)",
    "circularity_q": "폐합 + 좌표가 있는 경로 — 전부 비었다면 좌표나 폐합에 문제가 있다",
    "passed": "순환 실행(start_node == target_node) — 편도 전용 격자라면 정상",
    "gate_failed_on": "게이트 탈락 행 — 전부 통과했다면 비는 것이 정상",
    "within_time_budget": "params['time_budget_sec']를 넣은 실행",
    "waypoints_lost_clean": "경유지가 pruning으로 사라진 행 — 소실이 없었다면 0으로 채워짐",
    "waypoints_lost_repeated": "경유지가 pruning으로 사라진 행 — 소실이 없었다면 0으로 채워짐",
    # 성공 행의 error는 빈 문자열이고 CSV를 되읽으면 NaN이 된다. 전 행이 비었다는 것은
    # 실패가 한 건도 없었다는 뜻이므로 정상이다.
    "error": "실패·타임아웃 행 — 전부 성공했다면 비는 것이 정상",
}

_WAYPOINT_MARKER = "Waypoint"   # GRASP-Waypoint+*, Beam-Waypoint* (레거시 GRASP+VNS는 제외됨)
_GRASP_POOL_MARKER = "GRASP-Waypoint"


def _violations_for(frame: pd.DataFrame, columns, scope: str) -> list[str]:
    problems = []
    for column in columns:
        if column not in frame.columns:
            continue
        empty = int(frame[column].isna().sum())
        if empty:
            problems.append(
                f"{scope}: '{column}'이(가) {empty}/{len(frame)}행에서 비어 있습니다"
            )
    return problems


def check(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    """(위반, 정보) 두 목록을 만든다."""
    violations: list[str] = []
    notes: list[str] = []

    missing = [c for c in RESULT_COLUMNS if c not in df.columns]
    if missing:
        violations.append(f"스키마 누락: RESULT_COLUMNS 중 {missing}이(가) CSV에 없습니다")

    ok = df[df["status"] == "ok"] if "status" in df.columns else df.iloc[0:0]
    if ok.empty:
        notes.append("성공(status == 'ok') 행이 없어 값 검사를 건너뜁니다")
        return violations, notes

    violations += _violations_for(ok, ALWAYS_REQUIRED, "모든 solver")

    waypoint = ok[ok["algorithm"].str.contains(_WAYPOINT_MARKER, na=False)]
    if not waypoint.empty:
        violations += _violations_for(waypoint, WAYPOINT_SOLVER_REQUIRED, "경유지 solver")

    grasp_pool = ok[ok["algorithm"].str.startswith(_GRASP_POOL_MARKER, na=False)]
    if not grasp_pool.empty:
        violations += _violations_for(grasp_pool, GRASP_POOL_REQUIRED, "GRASP 풀 solver")

    for column in df.columns:
        if column in RESULT_COLUMNS and df[column].isna().all():
            owner = EMPTY_COLUMN_OWNERS.get(column, "이 컬럼을 채우는 solver")
            notes.append(f"전 행이 비어 있음: '{column}' (채웠어야 할 주체: {owner})")

    return violations, notes


def coverage_by_algorithm(df: pd.DataFrame) -> pd.DataFrame:
    """알고리즘별로 어떤 컬럼이 얼마나 채워졌는지 — 드리프트를 눈으로 확인할 때 쓴다."""
    if "algorithm" not in df.columns:
        return pd.DataFrame()
    tracked = [
        c for c in (*WAYPOINT_SOLVER_REQUIRED, *GRASP_POOL_REQUIRED,
                    "circularity_q", "passed", "within_time_budget")
        if c in df.columns
    ]
    if not tracked:
        return pd.DataFrame()
    return (
        df.groupby("algorithm")[tracked]
        .apply(lambda group: group.notna().mean())
        .round(3)
        .reset_index()
    )


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="결과 CSV 완전성 검사(이슈 K)")
    parser.add_argument("inputs", nargs="+", type=Path, help="검사할 결과 CSV")
    parser.add_argument(
        "--show-coverage", action="store_true",
        help="알고리즘별 컬럼 채움 비율표를 함께 출력",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    failed = False

    for path in args.inputs:
        print(f"\n=== {path} ===")
        if not path.exists():
            print("[위반] 파일이 없습니다")
            failed = True
            continue

        df = pd.read_csv(path)
        algorithms = df["algorithm"].nunique() if "algorithm" in df.columns else 0
        print(f"{len(df)}행, 컬럼 {len(df.columns)}개, 알고리즘 {algorithms}종")

        violations, notes = check(df)
        for note in notes:
            print(f"[정보] {note}")
        for violation in violations:
            print(f"[위반] {violation}")

        if args.show_coverage:
            coverage = coverage_by_algorithm(df)
            if not coverage.empty:
                print("\n알고리즘별 컬럼 채움 비율:")
                print(coverage.to_string(index=False))

        if violations:
            failed = True
        else:
            print("[통과] 필수 컬럼이 모두 채워져 있습니다")

    if failed:
        print("\n검사 실패 — 위 위반을 확인하세요.")
        return 1
    print("\n검사 통과.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
