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

    0) 게이트 탈락 필터 — 그 조건에서 한 번도 합격하지 못한(pass_rate == 0) 후보는
       순위 경쟁에서 제외한다. 순위 항목이 아니라 참가 자격이다.
    1) circularity_q_rel 평균 내림차순     — 같은 조건에서 얼마나 원형에 가까운가
    2) distance_deviation_km 평균 오름차순 — 목표 거리를 얼마나 맞추는가
    3) repeated_edge_ratio 평균 오름차순   — 같은 길을 얼마나 덜 되짚는가

2026-09-11 변경 — pass_rate를 1순위에서 0순위(탈락 필터)로 내리고 circularity_q_rel을
1순위로 올렸다. 근거:
  - 합격 게이트 4항목 중 3항목(is_closed_loop / spike_count / repeated_edge_ratio)은
    회귀 감시·prune_dead_ends 개편 대비용이라 정상 동작에서 전 행 상수다. 실제로
    2026-09-10 실측 500행에서 셋 다 값이 하나뿐이었고, 게이트를 가른 것은
    distance_deviation_km 10건뿐이었다. 상수를 순위 1순위에 두면 전 알고리즘이 동점이
    되어 2순위가 단독으로 승자를 정한다 — 실제로 그렇게 정해지고 있었다.
  - 게이트는 "회귀를 잡는 장치"이지 "우열을 가리는 장치"가 아니다. 역할에 맞게 참가
    자격으로 옮기고, 우열은 순환 품질을 직접 재는 지표로 가린다.

circularity_q를 절대값이 아니라 조건별 정규화값(circularity_q_rel)으로 쓰는 이유:
도보망에서 달성 가능한 Q의 상한이 조건마다 다르고 아직 이론값이 없다(config.py의
OBSERVED_CIRCULARITY_Q_MAX_RANGE 참고). 같은 조건에서 관측된 최댓값으로 나누면 상한을
몰라도 "누가 더 원형인가"는 흔들리지 않는다.
⚠ 그래서 circularity_q_rel은 순위 전용이다. 비교 대상 집합이 바뀌면 분모가 바뀌므로
  탈락 기준(절대 임계값)으로는 절대 쓰지 말 것 — 그 임계값은 사람 라벨링으로만 정해진다.

cost는 solver마다 정의가 달라 애초에 비교 대상이 아니다.

━━ 읽을 때 반드시 지킬 것 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 품질 평균은 성공한 실행만으로 계산된다. 어려운 조건에서 실패하는 알고리즘일수록
  쉬운 케이스만 남아 품질이 좋아 보이므로, pass_rate 없이 품질 평균만 읽지 말 것.
  그래서 "짝지은 비교"(모든 알고리즘이 성공한 조건으로만 한정) 표를 따로 낸다.
- 타임아웃 행의 elapsed_sec은 실제 소요가 아니라 제한시간에서 잘린(censored) 값이다.
  시간 통계에서는 제외하고, 몇 건이 잘렸는지 별도로 표기한다.
- 조건당 시드 10개에서 p95는 최댓값과 같아진다(stats.percentile docstring 참고).
  그래서 p95는 조건 단위가 아니라 알고리즘 전체를 모은 뒤에만 낸다.
- n_runs는 독립 표본 수가 아니다. 조건 10개 × 시드 10개 = 100행이면 실제 독립 단위는
  조건 10개다. 알고리즘별 표에 n_conditions·n_seeds_per_condition을 함께 내는 이유이며,
  std·p95는 조건 간 난이도 차이와 시드 변동이 섞인 값으로 읽어야 한다.
- 알고리즘 간 차이는 짝지은 순열검정(paired_tests)으로 확인한다. 평균이 달라 보여도
  조건 수가 적으면 우연일 수 있고, 조건 10개 수준에서는 그 구분이 눈으로 되지 않는다.
- 계산량은 astar_calls 단독으로 보지 말 것. pool_cache_miss 1회는 cutoff SSSP 1회로
  A* 1회와 단위가 다르다(실측 27.5배). search_work가 둘을 공통 단위로 환산한 값이다.

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

from benchmarks.config import SSSP_TO_LOOKUP_RATIO, TIME_BUDGET_REFERENCE_SEC
from benchmarks.results import RESULT_COLUMNS
from benchmarks.stats import paired_permutation_test, percentile


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
    # 조건별 최댓값으로 정규화한 원형성. 순위 규칙 1순위이며 add_derived_columns()가 만든다.
    Metric("circularity_q_rel", higher_is_better=True),
)

# 3계층 비용.
#
# 계산량 지표를 셋으로 나눠 두는 이유(2026-09-11):
#   astar_calls만 보면 계산량을 크게 오판한다. 실측(500행)에서 GRASP-Waypoint+ALNS는
#   astar_calls 96회로 +VNS(2,245회)의 1/23이지만 실제 시간은 61초 대 95초로 1.6배
#   차이일 뿐이었다. 빠진 것이 둘이다 —
#     (1) cache_hits : RESULT_COLUMNS에 있는데 이 표에 없어서 집계에서 통째로 누락돼
#         있었다. Local(조회 2,834회, 7.1초)과 VND(조회 10,804회, 17.6초)는 astar_calls가
#         321 대 328로 사실상 같아 astar_calls만으로는 2.5배 시간차를 설명할 수 없다.
#     (2) pool_cache_misses : 1회가 cutoff SSSP 1회라 A* 1회와 단위가 다르다.
#   path_lookups와 search_work가 그 둘을 각각 메운다. 회귀 설명력은 astar_calls 단독
#   R²=0.238 → search_work R²=0.686이다(config.SSSP_TO_LOOKUP_RATIO 주석 참고).
#
# elapsed_sec 계열은 6워커 병렬 풀에서 측정돼 환경 의존적이므로, 기계 독립적인
# search_work를 계산량의 1차 근거로 볼 것.
COST_METRICS = (
    Metric("elapsed_sec", higher_is_better=False, censored_by_timeout=True),
    Metric("find_path_sec", higher_is_better=False, censored_by_timeout=True),
    Metric("astar_calls", higher_is_better=False),
    Metric("cache_hits", higher_is_better=False),
    Metric("pool_cache_misses", higher_is_better=False),
    Metric("path_lookups", higher_is_better=False),
    Metric("search_work", higher_is_better=False),
)

# 2계층 원형성 대리 지표. circularity_q와의 상관 검증(이슈 H) 대상이라 같이 낸다.
PROXY_METRICS = (
    Metric("waypoint_separation_m", higher_is_better=True),
    Metric("segment_balance_ratio", higher_is_better=True),
)

ALL_METRICS = (*QUALITY_METRICS, *COST_METRICS, *PROXY_METRICS)

# raw CSV에는 없고 add_derived_columns()가 만드는 컬럼. 누락 경고 대상에서 제외한다.
DERIVED_COLUMNS = frozenset({"path_lookups", "search_work", "circularity_q_rel"})

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

# 순위는 품질만으로 매긴다. pass_rate는 순위 항목이 아니라 참가 자격(_GATE_COLUMN)이다 —
# 이유는 모듈 docstring "순위 규칙" 참고.
_RANKING_COLUMNS = (
    "circularity_q_rel_mean", "distance_deviation_km_mean", "repeated_edge_ratio_mean",
)
_RANKING_ASCENDING = (False, True, True)  # 원형성만 높을수록 좋다
_GATE_COLUMN = "pass_rate"


def _is_knob_column(column: str) -> bool:
    return bool(_KNOB_PATTERN.match(column)) and column not in _RESULT_SCHEMA_COLUMNS


def condition_columns(df: pd.DataFrame) -> list[str]:
    """이 CSV에서 조건을 식별하는 컬럼들."""
    columns = [c for c in _CONDITION_CANDIDATES if c in df.columns]
    columns += [c for c in df.columns if _is_knob_column(c)]
    return columns


def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """raw 행에서 파생 지표를 만든다. 집계 전에 한 번만 호출한다.

    만드는 것:
      path_lookups      = astar_calls + cache_hits
          경로 조회 총 횟수. 캐시에 맞은 조회도 비용이 0은 아니고(경로 복사·비용 합산),
          무엇보다 지역탐색이 얼마나 많은 이웃을 평가했는지를 이 값이 서술한다.
      search_work       = path_lookups + SSSP_TO_LOOKUP_RATIO * pool_cache_misses
          서로 다른 두 연산을 공통 단위로 환산한 계산량. 기계 독립적이므로 알고리즘 간
          계산량 비교는 이 값으로 한다.
      circularity_q_rel = circularity_q / (같은 조건에서 관측된 circularity_q 최댓값)
          조건별 정규화 원형성. 도보망의 Q 상한이 조건마다 다르고 이론값이 없어서,
          절대값 대신 같은 조건 안에서의 상대 위치로 비교한다.

    ⚠ circularity_q_rel의 분모는 "이 CSV에 담긴 알고리즘들이 그 조건에서 낸 최댓값"이다.
      비교 대상이 바뀌면 값이 바뀌므로 순위에만 쓰고 탈락 기준으로는 쓰지 않는다.
      성공 행이 하나도 없는 조건은 분모가 없어 NaN으로 남는다.
    """
    work = df.copy()

    if {"astar_calls", "cache_hits"} <= set(work.columns):
        calls = pd.to_numeric(work["astar_calls"], errors="coerce")
        hits = pd.to_numeric(work["cache_hits"], errors="coerce")
        work["path_lookups"] = calls.fillna(0) + hits.fillna(0)
        # 두 컬럼이 모두 비어 있던 행(레거시 solver)은 0이 아니라 미측정이다 — 0으로 두면
        # 계산량을 보고하지 않는 알고리즘이 '가장 싼 알고리즘'으로 집계된다.
        work.loc[calls.isna() & hits.isna(), "path_lookups"] = None

    if "path_lookups" in work.columns and "pool_cache_misses" in work.columns:
        misses = pd.to_numeric(work["pool_cache_misses"], errors="coerce")
        work["search_work"] = work["path_lookups"] + SSSP_TO_LOOKUP_RATIO * misses.fillna(0)

    keys = condition_columns(work)
    if "circularity_q" in work.columns and keys:
        ok = work["status"] == "ok" if "status" in work.columns else True
        best = work.where(ok)["circularity_q"].groupby(
            [work[key] for key in keys], dropna=False
        ).transform("max")
        work["circularity_q_rel"] = work["circularity_q"] / best.where(best > 0)

    return work


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

    # 파생 지표는 add_derived_columns()가 나중에 만든다 — raw CSV에 없는 것이 정상이므로
    # 누락 경고 대상에서 뺀다.
    missing = [
        m.column for m in ALL_METRICS
        if m.column not in merged.columns and m.column not in DERIVED_COLUMNS
    ]
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
    keys = condition_columns(df)
    rows = []

    for algorithm, group in df.groupby("algorithm", dropna=False):
        row = {"algorithm": algorithm}
        row["n_runs"] = len(group)
        # n_runs는 독립 표본 수가 아니다 — 조건 하나에서 시드를 여러 번 돌린 행이 섞여
        # 있다. std·p95를 읽을 때 실제 독립 단위가 몇 개인지 알 수 있도록 함께 낸다.
        row["n_conditions"] = group.groupby(keys, dropna=False).ngroups if keys else None
        row["n_seeds_per_condition"] = (
            round(len(group) / row["n_conditions"], 2) if row["n_conditions"] else None
        )
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

    게이트는 순위 항목이 아니라 참가 자격이다 — 그 조건에서 한 번도 합격하지 못한
    후보(pass_rate == 0)는 아예 경쟁에서 뺀다. 품질 평균은 성공 행만으로 계산되므로,
    전부 불합격한 알고리즘을 그대로 두면 "쉬운 시드에서만 좋았던 값"으로 이길 수 있다.
    """
    keys = _condition_keys_of(condition_df)
    usable = [c for c in _RANKING_COLUMNS if c in condition_df.columns]
    if not keys or not usable or condition_df.empty:
        return pd.DataFrame()

    ascending = [asc for col, asc in zip(_RANKING_COLUMNS, _RANKING_ASCENDING) if col in usable]

    eligible = condition_df
    if _GATE_COLUMN in condition_df.columns:
        gate = condition_df[_GATE_COLUMN]
        eligible = condition_df[gate.isna() | (gate > 0)]
        if eligible.empty:
            return pd.DataFrame()

    wins = []
    for _, group in eligible.groupby(keys, dropna=False):
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
    실제 동일 예산 비교는 search_work를 맞춘 조건으로 다시 실행해야 얻는다.

    기준 지표가 astar_calls에서 search_work로 바뀐 이유(2026-09-11): astar_calls는
    캐시 조회와 cutoff SSSP를 세지 않아 계산량을 크게 오판한다. 실측에서 ALNS와 VNS의
    astar_calls 비율은 23.4배였지만 실제 시간 비율은 1.6배였고, search_work 비율은
    1.4배로 시간과 일치했다.
    """
    column = "search_work_mean" if "search_work_mean" in algorithm_df.columns else "astar_calls_mean"
    if column not in algorithm_df.columns:
        return "[예산] 계산량 컬럼이 없어 예산 비교를 생략합니다."

    calls = algorithm_df.set_index("algorithm")[column].dropna()
    calls = calls[calls > 0]
    if len(calls) < 2:
        return "[예산] 비교할 알고리즘이 부족합니다."

    ratio = calls.max() / calls.min()
    lines = [
        f"[예산] 알고리즘별 평균 {column[:-5]}: "
        + ", ".join(f"{name}={value:,.0f}" for name, value in calls.sort_values().items()),
        f"[예산] 최대/최소 비율 = {ratio:.1f}배",
    ]
    if column == "astar_calls_mean":
        lines.append(
            "[주의] search_work가 없어 astar_calls로 비교했습니다. astar_calls는 캐시 조회와 "
            "cutoff SSSP를 세지 않아 계산량을 크게 오판합니다(실측 R²=0.238) — "
            "cache_hits·pool_cache_misses가 있는 CSV로 다시 집계하세요."
        )
    if ratio > 2:
        lines.append(
            "[경고] 탐색 예산이 2배 넘게 차이납니다. 이 상태의 품질 비교는 '알고리즘이 좋은 것'이 아니라 "
            f"'예산이 큰 것'을 고를 수 있습니다. 결론을 내기 전에 {column[:-5]}를 맞춘 조건으로 "
            "재실행하세요 — 집계로는 보정할 수 없습니다."
        )
    return "\n".join(lines)


def survival_by_budget(df: pd.DataFrame, budgets=TIME_BUDGET_REFERENCE_SEC) -> pd.DataFrame:
    """예산선마다 알고리즘별 생존율(그 시간 안에 끝난 실행의 비율).

    동기 요청에서는 평균이 아니라 최악값이 예산을 정한다 — 사용자 한 명이 평균의 세 배를
    기다리면 그 사람은 이탈한다. 그래서 최악값(worst)을 함께 낸다.

    예산선을 하나로 고정하지 않고 여러 개를 한 번에 내는 이유: 예산은 제품 결정이라
    나중에 바뀔 수 있는데, 그때마다 격자를 다시 돌리는 것은 낭비다. 이 표가 있으면
    예산이 바뀌어도 다시 읽기만 하면 된다.

    분모는 그 알고리즘의 전체 실행 수다(실패·타임아웃 포함) — 실패는 예산 안에 든 것이
    아니므로 분모에서 빼면 생존율이 부풀려진다.
    """
    if "elapsed_sec" not in df.columns or df.empty:
        return pd.DataFrame()

    rows = []
    for algorithm, group in df.groupby("algorithm", dropna=False):
        ok = group[group["status"] == "ok"] if "status" in group.columns else group
        elapsed = ok["elapsed_sec"].dropna()
        row = {
            "algorithm": algorithm,
            "n_runs": len(group),
            "elapsed_mean": elapsed.mean() if len(elapsed) else None,
            "elapsed_worst": elapsed.max() if len(elapsed) else None,
        }
        for budget in budgets:
            row[f"survive_{budget:g}s"] = (
                round((elapsed <= budget).sum() / len(group), 4) if len(group) else None
            )
        rows.append(row)

    return pd.DataFrame(rows).sort_values("algorithm").reset_index(drop=True)


def quality_under_budget(df: pd.DataFrame, budget: float) -> pd.DataFrame:
    """예산 안에 든 실행만으로 본 품질.

    ⚠ 생존 편향이 있다. 예산이 빡빡할수록 쉬운 조건만 남으므로, 같은 알고리즘이라도
      예산을 올리면 품질 평균이 함께 움직인다(실측: GRASP-Waypoint+Local이 5초 Q=0.340,
      30초 Q=0.417). 생존율이 1.0이 아닌 행의 품질은 그 알고리즘의 실력이 아니라
      "쉬운 조건에서의 실력"으로 읽어야 한다 — 그래서 생존율을 같은 표에 함께 낸다.
    """
    if "elapsed_sec" not in df.columns or df.empty:
        return pd.DataFrame()

    ok = df[df["status"] == "ok"] if "status" in df.columns else df
    total = df.groupby("algorithm", dropna=False).size()
    within = ok[ok["elapsed_sec"] <= budget]
    if within.empty:
        return pd.DataFrame()

    aggregations = {"n_within": ("elapsed_sec", "size"), "elapsed_worst": ("elapsed_sec", "max")}
    for column, name in (
        ("distance_deviation_km", "distance_deviation_km_mean"),
        ("circularity_q", "circularity_q_mean"),
        ("circularity_q_rel", "circularity_q_rel_mean"),
        ("repeated_edge_ratio", "repeated_edge_ratio_mean"),
    ):
        if column in within.columns:
            aggregations[name] = (column, "mean")

    table = within.groupby("algorithm", dropna=False).agg(**aggregations).reset_index()
    table.insert(1, "survival", [
        round(n / total.get(a, 0), 4) if total.get(a, 0) else None
        for a, n in zip(table["algorithm"], table["n_within"])
    ])
    return table.sort_values("algorithm").reset_index(drop=True)


def paired_tests(condition_df: pd.DataFrame, metric: str = _RANKING_COLUMNS[0]) -> pd.DataFrame:
    """알고리즘 쌍마다 짝지은 순열검정을 돌린다.

    같은 조건에서 두 알고리즘의 지표 차이를 모아, 부호가 우연인지 검정한다. 조건 수가
    적을 때(10개 수준) 평균 차이만 보고 "더 낫다"고 말하는 것을 막는 장치다.

    ⚠ 여러 쌍을 동시에 검정하므로 다중비교 문제가 있다. 쌍이 많으면 p-value를 그대로
      읽지 말고 Bonferroni(α/쌍 수) 같은 보정을 적용할 것 — 여기서는 보정 전 값을 내고
      쌍 수(n_pairs)를 함께 보고한다.
    """
    keys = _condition_keys_of(condition_df)
    if not keys or metric not in condition_df.columns or condition_df.empty:
        return pd.DataFrame()

    pivot = condition_df.pivot_table(index=keys, columns="algorithm", values=metric, dropna=False)
    algorithms = sorted(pivot.columns)
    if len(algorithms) < 2:
        return pd.DataFrame()

    rows = []
    for i, left in enumerate(algorithms):
        for right in algorithms[i + 1:]:
            pair = pivot[[left, right]].dropna()
            p_value, n, mean_difference = paired_permutation_test(pair[left] - pair[right])
            rows.append({
                "A": left, "B": right, "지표": metric, "n_conditions": n,
                "평균차(A-B)": mean_difference, "p_value": p_value,
                "유의(α=0.05)": "예" if p_value is not None and p_value < 0.05 else "아니오",
            })

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["n_pairs"] = len(frame)
    return frame


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

    df = add_derived_columns(df)

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
    ranking_source = paired_df if kept_conditions else condition_df
    wins_df = win_rates(ranking_source)
    tests_df = paired_tests(ranking_source)
    survival_df = survival_by_budget(df)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    condition_df.to_csv(args.out_dir / "aggregate_by_condition.csv", index=False)
    algorithm_df.to_csv(args.out_dir / "aggregate_by_algorithm.csv", index=False)
    if not wins_df.empty:
        wins_df.to_csv(args.out_dir / "aggregate_win_rates.csv", index=False)
    if not tests_df.empty:
        tests_df.to_csv(args.out_dir / "aggregate_paired_tests.csv", index=False)
    if not survival_df.empty:
        survival_df.to_csv(args.out_dir / "aggregate_budget_survival.csv", index=False)

    _print_section(
        "알고리즘별 전체 요약 (모든 조건·시드 합산)",
        algorithm_df,
        [
            "algorithm", "n_runs", "n_conditions", "n_seeds_per_condition",
            "n_ok", "n_timeout", "pass_rate",
            "circularity_q_rel_mean", "circularity_q_rel_worst",
            "distance_deviation_km_mean", "distance_deviation_km_std",
            "distance_deviation_km_p95", "distance_deviation_km_worst",
            "repeated_edge_ratio_mean", "repeated_edge_ratio_worst",
            "circularity_q_mean", "circularity_q_worst",
            "elapsed_sec_mean", "elapsed_sec_worst", "search_work_mean",
        ],
    )
    print(
        "[표본] n_runs는 독립 표본 수가 아닙니다 — 같은 조건을 시드만 바꿔 반복한 행이 섞여 "
        "있습니다. std·p95는 조건 간 난이도 차이와 시드 변동이 합쳐진 값이므로, 실제 독립 "
        "단위인 n_conditions와 함께 읽으세요."
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
        f"짝지은 비교 — 알고리즘 승률 (게이트 탈락 필터 후, 순위 규칙: {' → '.join(_RANKING_COLUMNS)})",
        wins_df,
    )
    print(
        "  게이트(pass_rate)는 순위 항목이 아니라 참가 자격입니다 — 그 조건에서 한 번도 합격하지 "
        "못한 후보는 경쟁에서 제외됩니다."
    )

    _print_section("짝지은 순열검정 — 알고리즘 쌍별 차이가 우연인가", tests_df)
    if not tests_df.empty:
        print(
            f"  쌍 {len(tests_df)}개를 동시에 검정했습니다(다중비교). p-value를 그대로 읽지 말고 "
            f"Bonferroni 보정선 α=0.05/{len(tests_df)}={0.05 / len(tests_df):.4f}과 비교하세요."
        )

    _print_section("시간 예산선별 생존율 (동기 요청이면 최악값이 예산을 정한다)", survival_df)
    for budget in TIME_BUDGET_REFERENCE_SEC:
        table = quality_under_budget(df, budget)
        if not table.empty:
            _print_section(f"예산 {budget:g}초 안에 든 실행만으로 본 품질", table)
    print(
        "\n  [생존 편향] 생존율이 1.0이 아닌 행의 품질은 그 알고리즘의 실력이 아니라 '예산 안에 "
        "들어온 쉬운 조건에서의 실력'입니다. 반드시 survival과 함께 읽으세요."
    )

    print()
    print(budget_report(algorithm_df))

    print(f"\n결과 저장 완료: {args.out_dir}/aggregate_by_condition.csv, aggregate_by_algorithm.csv")
    if not wins_df.empty:
        print(f"                {args.out_dir}/aggregate_win_rates.csv")
    if not tests_df.empty:
        print(f"                {args.out_dir}/aggregate_paired_tests.csv")
    if not survival_df.empty:
        print(f"                {args.out_dir}/aggregate_budget_survival.csv")


if __name__ == "__main__":
    main()
