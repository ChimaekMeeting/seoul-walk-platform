# run_all_scenarios.py

import argparse
import json
import multiprocessing
import os
import time

import networkx as nx
import pandas as pd

from benchmarks.config import ROUTE_ENGINE_DATASET
from benchmarks.benchmark import (
    _load_default_graph,
    _failed_row,
    _validate_solver_result,
    _compute_route_distance_km,
    _is_closed_loop,
    _count_spikes,
    _compute_edge_overlap_ratio,
    RESULT_COLUMNS,
    SOLVER_REGISTRY,
)
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.scoring.scoring_engine import precompute_scoring_features

# oneway 시나리오에서 target_km을 무시하고 순수 최단경로만 구하는 계열
SHORTEST_ALGOS = ["astar-oneway", "dijkstra-oneway", "bi-astar-oneway", "bi-dijkstra-oneway"]
# oneway 시나리오에서 target_km에 맞춰 우회 경로를 구하는 계열
ONEWAY_DETOUR_ALGOS = ["beam-oneway", "grasp-oneway", "alns-oneway"]
ONEWAY_ALGOS = SHORTEST_ALGOS + ONEWAY_DETOUR_ALGOS
CIRCULAR_ALGOS = ["beam-circular", "grasp-circular", "alns-circular"]

_CATEGORY_CHOICES = ("shortest", "oneway", "circular", "all")

# optimality_gap 계산용 — Dijkstra(oneway) cost를 최단거리 계열의 ground truth로 사용
_SHORTEST_ALGO_NAMES = {SOLVER_REGISTRY[key].name for key in SHORTEST_ALGOS}
_DIJKSTRA_ONEWAY_NAME = SOLVER_REGISTRY["dijkstra-oneway"].name

# quality_gain 계산용 — 편도우회/순환 계열이 profile 가중치를 얼마나 반영했는지 측정
_ONEWAY_DETOUR_ALGO_NAMES = {SOLVER_REGISTRY[key].name for key in ONEWAY_DETOUR_ALGOS}
_CIRCULAR_ALGO_NAMES = {SOLVER_REGISTRY[key].name for key in CIRCULAR_ALGOS}

# profile이 특히 강조하는 차원(profiles.py의 baseline 대비 가중치가 튀는 필드) → 그래프 edge의 raw feature 속성명
# child는 프로덕션 scoring_engine이 is_vehicle_caution로 처리하지만, 벤치마크 fixture에는 child_score가
# 그대로 있어서(benchmark.py _load_default_graph) 그걸 프록시로 쓴다.
_PROFILE_FOCUS_ATTR = {
    "nature": "nature_score",
    "safe": "safety_score",
    "landmark": "landmark_score",
    "child": "child_score",
}

# 레이어(차원)별 비교용 — 벤치마크 fixture(benchmark.py _load_default_graph)가 실제로 채워주는 차원만 포함.
# convenience/accessibility는 fixture에 없어서 항상 0이라 제외. slope_score는 fixture에서 모든 edge가
# 0.5로 고정돼 있어(실제 경사 데이터 없음) 이 차원의 quality_gain은 항상 0으로 나오는 게 정상이다.
_ALL_QUALITY_DIMS = {
    "safety": "safety_score",
    "nature": "nature_score",
    "slope": "slope_score",
    "landmark": "landmark_score",
    "child": "child_score",
}

_POOL_GRAPH = None  # 워커 프로세스 전역 — 워커당 1번만 채워짐(그래프 재전송 없음)


def _pool_worker_init():
    """워커 프로세스 시작 시 1회만 실행 — 그래프를 이 워커 메모리 안에 준비."""
    global _POOL_GRAPH
    _POOL_GRAPH = _load_default_graph()
    precompute_scoring_features(_POOL_GRAPH)


def _pool_worker_task(solver_key: str, start_node, target_node, params: dict) -> dict:
    """
    태스크마다 실행. solver 인스턴스·그래프를 매번 안 받고,
    solver_key로 SOLVER_REGISTRY에서 찾고 그래프는 워커 전역(_POOL_GRAPH)을 그대로 쓴다.
    """
    solver = SOLVER_REGISTRY[solver_key]
    target_km = params.get("target_km")
    time_budget_sec = params.get("time_budget_sec")

    t0 = time.perf_counter()
    try:
        raw_result = solver.solve(_POOL_GRAPH, start_node, target_node, params)
    except Exception as e:
        return _failed_row(solver, "failed", time.perf_counter() - t0, repr(e), target_km)

    elapsed = time.perf_counter() - t0

    try:
        result = _validate_solver_result(raw_result)
    except Exception as e:
        return _failed_row(solver, "failed", elapsed, str(e), target_km)

    distance_km = _compute_route_distance_km(_POOL_GRAPH, result["paths"])
    distance_deviation_km = (
        round(abs(distance_km - target_km), 4) if distance_km is not None and target_km is not None else None
    )
    within_time_budget = elapsed <= time_budget_sec if time_budget_sec is not None else None

    return {
        "algorithm": solver.name,
        "status": "ok",
        "elapsed_sec": round(elapsed, 6),
        "within_time_budget": within_time_budget,
        "cost": result["cost"],
        "overlap_ratio": result["overlap_ratio"],
        "distance_km": distance_km,
        "target_km": target_km,
        "distance_deviation_km": distance_deviation_km,
        "is_closed_loop": _is_closed_loop(result["paths"]),
        "spike_count": _count_spikes(result["paths"]),
        "edge_overlap_ratio": _compute_edge_overlap_ratio(result["paths"]),
        "find_path_sec": result.get("find_path_sec"),
        "error": "",
        "paths": result["paths"][0],  # quality_gain 계산용 — 최종 CSV 저장 전에 drop됨
    }


def _run_scenario_with_pool(pool, algos, start_node, target_node, params, timeout_sec=30.0) -> pd.DataFrame:
    """
    이미 떠 있는 워커 풀에 알고리즘별 태스크를 제출하고 결과를 모은다.
    타임아웃 시 해당 워커는 죽이지 않고 결과만 실패 처리한다(하드킬 포기 — 절충안).
    """
    async_results = {
        key: pool.apply_async(_pool_worker_task, args=(key, start_node, target_node, params))
        for key in algos
    }
    rows = []
    for key, ar in async_results.items():
        solver = SOLVER_REGISTRY[key]
        try:
            rows.append(ar.get(timeout=timeout_sec))
        except multiprocessing.TimeoutError:
            rows.append(_failed_row(
                solver, "timeout", timeout_sec,
                f"timeout after {timeout_sec}s (worker 강제종료 안 함 — 절충안)", params.get("target_km"),
            ))
    return pd.DataFrame(rows, columns=RESULT_COLUMNS + ["paths"])


def _add_optimality_gap(df: pd.DataFrame) -> pd.DataFrame:
    """
    최단거리 계열(SHORTEST_ALGOS)의 cost를 같은 시나리오의 Dijkstra(oneway) cost(ground truth)와
    비교해 optimality_gap = (algo_cost - dijkstra_cost) / dijkstra_cost 를 계산한다.
    0이면 Dijkstra와 동일한 비용(=최적), 양수면 최적보다 비싼 경로를 냈다는 뜻.
    이 시나리오에 Dijkstra(oneway)가 없거나 실패했으면(ground truth 없음) 전부 NaN.
    """
    dijkstra_rows = df[(df["algorithm"] == _DIJKSTRA_ONEWAY_NAME) & (df["status"] == "ok")]
    dijkstra_cost = dijkstra_rows["cost"].iloc[0] if not dijkstra_rows.empty else None

    def _gap(row):
        if (
            dijkstra_cost is None
            or dijkstra_cost <= 0
            or row["algorithm"] not in _SHORTEST_ALGO_NAMES
            or row["status"] != "ok"
        ):
            return float("nan")
        return round((row["cost"] - dijkstra_cost) / dijkstra_cost, 6)

    df["optimality_gap"] = df.apply(_gap, axis=1)
    return df


def _add_used_fallback(df: pd.DataFrame) -> pd.DataFrame:
    """
    편도우회 계열(ONEWAY_DETOUR_ALGOS)이 실제로 우회했는지, 아니면 우회 실패해서
    자기 자신의 base_shortest(custom_score 최단경로)로 그냥 대체했는지를 표시한다.
    overlap_ratio(자기 base_shortest와 겹치는 거리 비율)가 사실상 1.0이면 대체된 것으로 본다
    ("beam search 후보가 비어 최단 경로로 대체합니다" 류 로그가 찍히는 그 케이스).
    circular/최단거리 계열은 overlap_ratio가 이 의미로 안 쓰여서(circular는 0.0 고정,
    최단거리 계열은 애초에 우회 개념이 없음) NaN.
    """
    def _fallback(row):
        if row["status"] != "ok" or row["algorithm"] not in _ONEWAY_DETOUR_ALGO_NAMES:
            return float("nan")
        return bool(row["overlap_ratio"] >= 0.999)

    df["used_fallback"] = df.apply(_fallback, axis=1)
    return df


def _path_focus_avg(graph: nx.Graph, path: list, focus_attr: str) -> float | None:
    """path를 따라 length로 가중평균한 focus_attr(0~1, 높을수록 좋음) 값을 반환한다."""
    if not path or len(path) < 2:
        return None
    total_len = 0.0
    weighted = 0.0
    for i in range(len(path) - 1):
        edge = graph.get_edge_data(path[i], path[i + 1]) or {}
        length = edge.get("length", 0.0) or 0.0
        total_len += length
        weighted += length * (edge.get(focus_attr, 0.0) or 0.0)
    return weighted / total_len if total_len > 0 else None


def _safe_shortest_path(graph: nx.Graph, start_node: int, target_node: int) -> list | None:
    try:
        return nx.shortest_path(graph, start_node, target_node, weight="length")
    except nx.NetworkXNoPath:
        return None


def _add_quality_gain_columns(
    df: pd.DataFrame,
    graph: nx.Graph,
    base_path_lookup,
    focus_attr: str | None,
    algo_names: set,
) -> pd.DataFrame:
    """
    algo_names에 속한 행에 대해, 선택 경로가 기준선(base_path_lookup(row)) 대비 각 차원에서
    얼마나 나아졌는지를 컬럼으로 채운다.

    - quality_gain_<dim> (_ALL_QUALITY_DIMS 전 차원): 선택 경로의 차원별 평균 - 기준선의 차원별 평균.
      양수면 기준선보다 그 차원이 실제로 좋아졌다는 뜻, 0 이하면 나아진 게 없다는 뜻.
    - quality_gain: 위 중 profile이 특히 강조하는 한 차원(focus_attr)만 뽑은 요약값(요약표용).
      focus_attr이 없는 profile(default 등)이면 NaN.

    base_path_lookup(row) -> 그 행과 비교할 기준 경로(list) 또는 None(비교 불가 시 NaN).
    행별로 다른 기준선을 줄 수 있게 콜백으로 분리했다 — oneway는 시나리오 전체가 같은 기준선(순수
    최단경로)을 쓰지만, circular은 알고리즘별로 다른 기준선(같은 알고리즘의 중립 가중치 재실행 결과)을 쓴다.
    """
    def _row_gain(row, attr):
        if row["status"] != "ok" or row["algorithm"] not in algo_names:
            return float("nan")
        base_path = base_path_lookup(row)
        if not base_path:
            return float("nan")
        base_avg = _path_focus_avg(graph, base_path, attr)
        path_avg = _path_focus_avg(graph, row["paths"], attr)
        if base_avg is None or path_avg is None:
            return float("nan")
        return round(path_avg - base_avg, 6)

    for dim, attr in _ALL_QUALITY_DIMS.items():
        df[f"quality_gain_{dim}"] = df.apply(lambda row, a=attr: _row_gain(row, a), axis=1)

    df["quality_gain"] = (
        df.apply(lambda row: _row_gain(row, focus_attr), axis=1)
        if focus_attr is not None
        else float("nan")
    )
    return df


_SHORTEST_SUMMARY_COLS = [
    "시도횟수", "성공", "평균초", "최대초", "평균find_path초",
    "평균거리편차km", "평균우회도", "평균자기중복", "평균optimality_gap", "최대optimality_gap",
]
_DETOUR_SUMMARY_COLS = [
    "시도횟수", "성공", "평균초", "최대초",
    "평균거리편차km", "평균우회도", "평균자기중복", "평균quality_gain", "우회실패율",
] + [f"gain_{d}" for d in _ALL_QUALITY_DIMS]
_CIRCULAR_SUMMARY_COLS = [
    "시도횟수", "성공", "평균초", "최대초",
    "평균거리편차km", "평균우회도", "평균자기중복", "평균quality_gain",
] + [f"gain_{d}" for d in _ALL_QUALITY_DIMS]


def _md_table(df: pd.DataFrame, columns: list[str]) -> str:
    """summary(index=algorithm)의 일부 컬럼을 마크다운 표 문자열로 만든다."""
    header = ["algorithm"] + columns
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] + ["--:"] * len(columns)) + "|",
    ]
    for algo, row in df[columns].iterrows():
        cells = [algo] + [
            "" if pd.isna(v) else (f"{v:.4f}" if isinstance(v, float) else str(v))
            for v in row
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _build_markdown_report(summary: pd.DataFrame, scenario_count: int) -> str:
    """계열별(편도최단/편도우회/순환)로 표를 나누고 컬럼 뜻 glossary까지 붙인 마크다운 리포트를 만든다."""
    lines = [f"# 벤치마크 결과 요약 ({scenario_count}개 시나리오)", ""]

    lines += [
        "## 분류 기준 (`run_all_scenarios.py`)",
        "",
        "| 구분 | 대상 알고리즘 | 정의 |",
        "|---|---|---|",
        f"| 편도최단 (`SHORTEST_ALGOS`) | {', '.join(sorted(_SHORTEST_ALGO_NAMES))} | "
        "oneway 시나리오에서 `target_km`을 아예 무시하고 순수 최단경로만 구함 |",
        f"| 편도우회 (`ONEWAY_DETOUR_ALGOS`) | {', '.join(sorted(_ONEWAY_DETOUR_ALGO_NAMES))} | "
        "oneway 시나리오에서 `target_km`에 맞춰 일부러 우회 경로를 구함 |",
        f"| 순환 (`CIRCULAR_ALGOS`) | {', '.join(sorted(_CIRCULAR_ALGO_NAMES))} | "
        "circular 시나리오(출발=도착)에서 `target_km`짜리 순환 경로를 구함 |",
        "",
        "---",
        "",
    ]

    section_no = 1
    shortest_present = _SHORTEST_ALGO_NAMES & set(summary.index)
    if shortest_present:
        lines += [
            f"## {section_no}. 편도최단 (target_km 무시, 순수 최단경로)",
            "",
            _md_table(summary.loc[sorted(shortest_present)], _SHORTEST_SUMMARY_COLS),
            "",
            "> `평균quality_gain`, `우회실패율`은 이 계열에 해당 없음(전부 NaN)이라 표에서 제외.",
            "> `평균거리편차km`은 목표거리 달성도가 아니라 자연 최단거리와 target_km의 우연한 차이일 "
            "뿐이므로, 편도우회/순환 계열과 나란히 비교하면 안 됨.",
            "",
            "---",
            "",
        ]
        section_no += 1

    detour_present = _ONEWAY_DETOUR_ALGO_NAMES & set(summary.index)
    if detour_present:
        lines += [
            f"## {section_no}. 편도우회 (target_km에 맞춰 우회)",
            "",
            _md_table(summary.loc[sorted(detour_present)], _DETOUR_SUMMARY_COLS),
            "",
            "> `평균find_path초`, `optimality_gap`은 이 계열에 해당 없음(전부 NaN)이라 표에서 제외.",
            "> `평균quality_gain`은 순수 최단경로(weight=length) 대비 profile이 강조하는 한 차원의 "
            "개선폭, `gain_*`는 그걸 안전/자연/경사/랜드마크/아동친화 5개 차원 전부로 쪼갠 값. 0보다 커야 "
            "\"우회한 보람이 있었다\"는 뜻이고 default처럼 강조 차원이 없는 profile은 NaN.",
            "> `우회실패율`은 우회 후보가 없어서 자기 자신의 base_shortest로 그대로 대체된 비율.",
            "",
            "---",
            "",
        ]
        section_no += 1

    circular_present = _CIRCULAR_ALGO_NAMES & set(summary.index)
    if circular_present:
        lines += [
            f"## {section_no}. 순환 (출발=도착, target_km 순환 경로)",
            "",
            _md_table(summary.loc[sorted(circular_present)], _CIRCULAR_SUMMARY_COLS),
            "",
            "> `find_path초`, `optimality_gap`, `우회실패율`은 이 계열에 해당 없음(전부 NaN)이라 표에서 제외.",
            "> `평균quality_gain`/`gain_*`는 같은 알고리즘을 중립(default) 프로필로 한 번 더 돌린 결과 "
            "대비 개선폭(circular은 순수 최단경로 기준선이 없어서 자기 자신의 중립 버전과 비교). 시나리오가 "
            "이미 default profile이면 자기 자신과 비교라 항상 0.",
            "> 성공 < 시도횟수인 알고리즘은 일부 시나리오에서 실패(status != \"ok\")했다는 뜻.",
            "",
            "---",
            "",
        ]

    lines += [
        "## 컬럼 뜻 (코드 기준)",
        "",
        "| 컬럼 | 의미 / 계산식 | 출처 |",
        "|---|---|---|",
        "| 시도횟수 | 이 알고리즘이 돌아간 시나리오 개수(그룹 내 `status` 개수) | "
        "`groupby(...).agg(시도횟수=(\"status\",\"count\"))` |",
        "| 성공 | `status == \"ok\"`인 횟수. 실패·타임아웃은 제외 | 동일 |",
        "| 평균초 / 최대초 | `elapsed_sec`의 평균/최대. `solve()` 호출 자체의 순수 소요시간(프로세스 spawn "
        "오버헤드 제외) | `benchmark.py:_run_single`, `run_all_scenarios.py:_pool_worker_task` |",
        "| 평균find_path초 | `find_path_sec` 평균. solver가 스스로 내부 경로탐색 시간만 따로 잰 값(선택 "
        "필드) — 편도최단 계열만 이 값을 채워서 반환하고 나머지는 안 채워서 NaN | 각 solver의 `solve()` "
        "반환값 |",
        "| 평균거리편차km | `distance_deviation_km = \\|distance_km - target_km\\|`의 평균. "
        "`distance_km`은 solver 자기신고가 아니라 하네스가 그래프 edge `length`(m)를 직접 합산해 재계산한 "
        "실제 거리(km) | `benchmark.py:_compute_route_distance_km` |",
        "| 평균우회도 | `overlap_ratio` 평균. **solver 자기신고 값**(하네스가 그대로 신뢰). 편도최단·편도우회 "
        "계열은 \"이 경로가 같은 출발~도착의 base_shortest(custom_score 최단경로)와 겹치는 거리 비율\", "
        "순환 계열은 항상 0.0 고정 | `_oneway_engine_common.py:base_shortest_path_overlap_ratio` |",
        "| 평균자기중복 | `edge_overlap_ratio` 평균. **하네스가 경로 자체에서 재계산**한 값 — 대표 경로가 "
        "자기 구간을 몇 번이나 되짚어 지나가는지(무방향 기준, 왕복 잔가시 검출용) | "
        "`benchmark.py:_compute_edge_overlap_ratio` |",
        "| 평균/최대 optimality_gap | `(algo_cost - Dijkstra(oneway)_cost) / Dijkstra(oneway)_cost`. "
        "같은 시나리오의 Dijkstra(oneway) cost를 최적해(ground truth)로 두고 비교. 0이면 Dijkstra와 동일 "
        "비용. **편도최단 계열 전용** | `run_all_scenarios.py:_add_optimality_gap` |",
        "| 평균quality_gain | `선택 경로의 profile 강조 차원 평균 - 기준선의 같은 차원 평균`(길이로 "
        "가중평균). 편도우회는 기준선=순수 최단경로(weight=length), 순환은 기준선=같은 알고리즘의 "
        "중립(default) 재실행 결과 | `run_all_scenarios.py:_add_quality_gain_columns` |",
        "| gain_safety/nature/slope/landmark/child | `평균quality_gain`을 profile이 강조하는 한 차원만 "
        "보지 않고 전 차원으로 쪼갠 값(같은 기준선 대비). gain_slope는 fixture의 모든 edge가 "
        "slope_score=0.5 고정이라 항상 0이 정상 | `run_all_scenarios.py:_add_quality_gain_columns` |",
        "| 우회실패율 | `overlap_ratio >= 0.999`인 비율. 우회를 시도했지만 후보가 없어서 자기 자신의 "
        "base_shortest로 그대로 대체된(\"우회 실패\") 비율. **편도우회 계열 전용** | "
        "`run_all_scenarios.py:_add_used_fallback` |",
        "",
    ]

    return "\n".join(lines)


def _build_scenario_detail(result_df: pd.DataFrame) -> pd.DataFrame:
    """
    시나리오 x 알고리즘으로 cost/quality_gain/gain_<dim>을 피벗해, 요약표의 "전체 평균"이 아니라
    시나리오 하나하나에서 바로 비교할 수 있는 표를 만든다. 컬럼은 '<algorithm>__<metric>' 형태
    (예: 'Beam(oneway)__quality_gain', 'GRASP+VNS(oneway)__gain_safety').
    """
    metrics = ["cost", "quality_gain"] + [f"quality_gain_{d}" for d in _ALL_QUALITY_DIMS]
    detail = result_df.pivot_table(index=["scenario_id", "mode"], columns="algorithm", values=metrics)
    detail.columns = [f"{algo}__{metric}" for metric, algo in detail.columns]
    return detail[sorted(detail.columns)]


def _select_scenarios(scenarios: list, category: str) -> list[tuple[dict, list[str]]]:
    """
    category에 맞춰 (시나리오, 이번에 돌릴 algos) 쌍만 골라 반환한다.
    - shortest : oneway 시나리오만, target_km을 무시하는 최단경로 계열만
    - oneway   : oneway 시나리오만, target_km 기반 우회 계열만
    - circular : circular 시나리오만
    - all      : 기존과 동일(전체)
    """
    selected = []
    for case in scenarios:
        mode = case["mode"]
        if category == "all":
            algos = ONEWAY_ALGOS if mode == "oneway" else CIRCULAR_ALGOS
        elif category == "shortest":
            if mode != "oneway":
                continue
            algos = SHORTEST_ALGOS
        elif category == "oneway":
            if mode != "oneway":
                continue
            algos = ONEWAY_DETOUR_ALGOS
        elif category == "circular":
            if mode != "circular":
                continue
            algos = CIRCULAR_ALGOS
        else:
            raise ValueError(f"알 수 없는 category: {category}")
        selected.append((case, algos))
    return selected


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="route_engine.json 시나리오 전체 벤치마크 실행기")
    parser.add_argument(
        "--category",
        choices=_CATEGORY_CHOICES,
        default="all",
        help=(
            "실행할 알고리즘 그룹 선택. "
            "shortest=최단거리(target_km 무시), oneway=편도우회(target_km 기반), "
            "circular=순환, all=전체(기본값)"
        ),
    )
    return parser.parse_args(argv)


def main():
    args = parse_args()

    print("워커 풀 준비 중...", flush=True)
    t0 = time.perf_counter()
    pool = multiprocessing.get_context("spawn").Pool(processes=6, initializer=_pool_worker_init)
    print(f"워커 풀 준비 완료: {time.perf_counter() - t0:.1f}초", flush=True)

    graph = _load_default_graph()  # 부모 프로세스에선 노드 탐색(find_nearest_node)에만 사용
    utils = PathUtils(graph)

    with open(ROUTE_ENGINE_DATASET, encoding="utf-8") as f:
        dataset = json.load(f)

    selected = _select_scenarios(dataset["scenarios"], args.category)
    oneway_count = sum(1 for case, _ in selected if case["mode"] == "oneway")
    circular_count = sum(1 for case, _ in selected if case["mode"] == "circular")
    print(
        f"[category={args.category}] 시나리오 {len(selected)}개 테스트 "
        f"(oneway {oneway_count}개, circular {circular_count}개)\n",
        flush=True,
    )

    all_rows = []
    t_start = time.perf_counter()

    for i, (case, algos) in enumerate(selected, 1):
        mode = case["mode"]

        start_node = utils.find_nearest_node(case["start_lat"], case["start_lon"])
        target_node = utils.find_nearest_node(case["end_lat"], case["end_lon"]) if mode == "oneway" else start_node

        print(f"[{i}/{len(selected)}] {case['id']} ({mode}, profile={case['profile']}, target_km={case['target_km']}) 시작...", flush=True)

        params = {"target_km": case["target_km"], "profile": case["profile"]}
        df = _run_scenario_with_pool(pool, algos, start_node, target_node, params, timeout_sec=30.0)
        df = _add_optimality_gap(df)
        df = _add_used_fallback(df)

        focus_attr = _PROFILE_FOCUS_ATTR.get(case["profile"])
        if mode == "oneway":
            # 기준선 = 순수 최단경로(weight=length, profile 무시) — 시나리오 전체가 같은 기준선을 씀
            base_path = _safe_shortest_path(graph, start_node, target_node)
            df = _add_quality_gain_columns(df, graph, lambda row: base_path, focus_attr, _ONEWAY_DETOUR_ALGO_NAMES)
        else:
            # circular은 "순수 최단경로" 개념이 없어서(start==end), 같은 알고리즘을 중립 프로필(default)로
            # 한 번 더 돌린 결과를 그 알고리즘의 기준선으로 쓴다. 시나리오 자체가 이미 default profile이면
            # 재실행 없이 자기 자신을 기준선으로 재사용한다(어차피 동일 입력이라 결과가 같음).
            if case["profile"] == "default":
                baseline_df = df
            else:
                neutral_params = {"target_km": case["target_km"], "profile": "default"}
                baseline_df = _run_scenario_with_pool(pool, algos, start_node, target_node, neutral_params, timeout_sec=30.0)
            baseline_paths = {
                row["algorithm"]: row["paths"]
                for _, row in baseline_df.iterrows()
                if row["status"] == "ok"
            }
            df = _add_quality_gain_columns(
                df, graph, lambda row: baseline_paths.get(row["algorithm"]), focus_attr, _CIRCULAR_ALGO_NAMES,
            )
        df.insert(0, "scenario_id", case["id"])
        df.insert(1, "mode", mode)
        all_rows.append(df)

        ok_count = (df["status"] == "ok").sum()
        print(f"  -> {ok_count}/{len(df)} ok", flush=True)

    pool.close()
    pool.join()

    result_df = pd.concat(all_rows, ignore_index=True)
    result_df = result_df.drop(columns=["paths"])  # quality_gain 계산에만 쓰고 CSV엔 안 남김
    out_path = "all_scenarios_results.csv"
    result_df.to_csv(out_path, index=False)

    print(f"\n전체 소요 시간: {time.perf_counter() - t_start:.1f}초")
    print(f"결과 저장 완료: {out_path}\n")

    summary = result_df.groupby("algorithm").agg(
        시도횟수=("status", "count"),
        성공=("status", lambda s: (s == "ok").sum()),
        평균초=("elapsed_sec", "mean"),
        최대초=("elapsed_sec", "max"),
        평균find_path초=("find_path_sec", "mean"),
        평균거리편차km=("distance_deviation_km", "mean"),
        평균우회도=("overlap_ratio", "mean"),
        평균자기중복=("edge_overlap_ratio", "mean"),
        평균optimality_gap=("optimality_gap", "mean"),
        최대optimality_gap=("optimality_gap", "max"),
        평균quality_gain=("quality_gain", "mean"),
        우회실패율=("used_fallback", "mean"),
        **{f"gain_{dim}": (f"quality_gain_{dim}", "mean") for dim in _ALL_QUALITY_DIMS},
    ).round(4)

    print("=== 알고리즘별 요약 (계열별 분할) ===")
    for title, algo_names, cols in [
        ("[1] 편도최단 (target_km 무시, 순수 최단경로)", _SHORTEST_ALGO_NAMES, _SHORTEST_SUMMARY_COLS),
        ("[2] 편도우회 (target_km에 맞춰 우회)", _ONEWAY_DETOUR_ALGO_NAMES, _DETOUR_SUMMARY_COLS),
        ("[3] 순환 (출발=도착, target_km 순환 경로)", _CIRCULAR_ALGO_NAMES, _CIRCULAR_SUMMARY_COLS),
    ]:
        present = algo_names & set(summary.index)
        if present:
            print(f"\n{title}")
            print(summary.loc[sorted(present), cols].to_string())

    report_dir = os.path.join("analysis", "route_engine")
    os.makedirs(report_dir, exist_ok=True)

    report_md = _build_markdown_report(summary, len(selected))
    report_path = os.path.join(report_dir, "benchmark_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"\n계열별 표 + 컬럼 glossary가 포함된 마크다운 리포트 저장 완료: {report_path}")

    detail = _build_scenario_detail(result_df)
    detail_path = os.path.join(report_dir, "benchmark_scenario_detail.csv")
    detail.to_csv(detail_path)
    print(f"시나리오별 상세(레이어별/전체 비용 비교) CSV 저장 완료: {detail_path}")


if __name__ == "__main__":
    main()
