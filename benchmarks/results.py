"""
benchmarks/results.py

벤치마크 결과 행(CSV 한 줄)의 단일 정의 지점.

이 모듈이 생긴 이유(2026-09-10):
    결과 행을 만드는 코드가 benchmark.py::_run_single()과 러너 4종(run_all_scenarios /
    run_alns_validation / run_min_separation_validation / run_geometry_validation)에
    복붙돼 있었다. 그래서 컬럼을 추가할 때마다 한두 곳이 빠졌고, 실제로
    num_waypoints_used / effective_waypoints_used / pool_cache_hits / pool_cache_misses
    네 컬럼이 러너 4종 전부에서 비어 있었다(열은 생기고 전 행 NaN).
    행 생성을 여기 한 곳으로 모으고, 행을 "RESULT_COLUMNS 전부를 None으로 깐 뒤 아는
    값만 덮어쓰는" 방식(_empty_row)으로 만들어 구조적으로 누락이 불가능하게 한다.
    앞으로 컬럼을 늘릴 때는 RESULT_COLUMNS와 아래 _OPTIONAL_*_KEYS 표만 고치면 되고,
    러너는 건드릴 필요가 없다.

지표 계산 원칙:
    solver의 자기 신고를 그대로 믿지 않고 최종 경로(paths)와 graph에서 하네스가 독립적으로
    재계산한다. 단 엔진이 최종 경로에서 직접 계산해 넘겨준 값이 있으면 그쪽을 우선한다 —
    엔진과 하네스가 서로 다른 값을 내는 상황을 만들지 않기 위해서다.
"""

import math
import time
from typing import Optional

from benchmarks.config import (
    MAX_DISTANCE_DEVIATION_KM,
    MAX_REPEATED_EDGE_RATIO,
    MAX_SPIKE_COUNT,
)
from src.route_engine.waypoint_route_builder import edge_overlap_ratio

REQUIRED_RESULT_KEYS = ("paths", "cost")
_EARTH_RADIUS_M = 6371008.8  # WGS84 평균 반지름

RESULT_COLUMNS = [
    # --- 식별·실행 상태 ---
    "algorithm", "status", "elapsed_sec", "within_time_budget",

    # --- 1계층: 최종 경로에서 직접 관측되는 값 (합격 게이트가 쓰는 지표) ---
    # 경유지 분해에 의존하지 않으므로, pruning이 경유지를 지웠는지와 무관하게
    # "사용자에게 실제로 전달되는 경로"를 서술한다.
    "distance_km", "target_km", "distance_deviation_km",
    "is_closed_loop", "spike_count", "repeated_edge_ratio", "circularity_q",
    # 위 관측값들이 config.py의 임계값을 전부 통과했는지(순환 행만 판정, 편도는 None).
    # gate_failed_on은 떨어진 항목 이름을 쉼표로 묶은 문자열 — 집계에서 "무엇 때문에
    # 떨어졌는가"를 세려면 불리언 하나로는 부족하다. evaluate_gate() 참고.
    "passed", "gate_failed_on",

    # --- solver 자기 신고 (알고리즘 간 비교 금지) ---
    # cost: wp 계열은 거리(m), 레거시 순환 계열은 누적 custom_score라 단위·스케일이 다르다.
    #       같은 알고리즘의 조건 간 비교에만 쓰고, 알고리즘끼리 나란히 비교하지 말 것.
    # overlap_ratio: "베이스 최단경로와 겹치는 비율"로 repeated_edge_ratio와 개념이 다른
    #       편도(oneway) 전용 지표다. 순환 solver는 이 값을 아예 보고하지 않으므로 None이다.
    "cost", "overlap_ratio",

    # --- 3계층: 비용 ---
    "find_path_sec", "astar_calls", "cache_hits", "pool_cache_hits", "pool_cache_misses",

    # --- 4계층: 진단 (결정 근거로 쓰지 않음) ---
    # 아래 segment_*/waypoint_*/is_degenerate_loop는 최종 경로가 아니라 "선언한 경유지
    # 분해"를 다시 걸어서 계산한 값이다(grasp_waypoint_common.compute_route_geometry_metrics).
    # pruning이 경유지를 지운 행에서는 최종 경로와 어긋나므로 게이트에 쓰지 않는다.
    "selection_status", "feasible",
    "segment_p1_p2_m", "segment_p2_p3_m", "segment_p3_p1_m",
    "waypoint_separation_m", "min_waypoint_separation_m",
    "waypoint_angle_diff_deg", "segment_balance_ratio", "is_degenerate_loop",
    "num_waypoints_used", "effective_waypoints_used",
    "prune_branch_count", "prune_branch_length_m",
    "prune_clean_branch_count", "prune_clean_branch_length_m",
    "waypoints_lost_clean", "waypoints_lost_repeated",
    "alns_operator_stats",

    "error",
]

# solver가 선택적으로 채워 보내는 필드. 타입 검증과 행 복사가 이 목록만 보고 돌아간다.
_OPTIONAL_INT_KEYS = (
    "astar_calls", "cache_hits", "pool_cache_hits", "pool_cache_misses",
    "num_waypoints_used", "effective_waypoints_used",
    "prune_branch_count", "prune_clean_branch_count",
    "waypoints_lost_clean", "waypoints_lost_repeated",
)
_OPTIONAL_FLOAT_KEYS = (
    "find_path_sec", "overlap_ratio",
    "segment_p1_p2_m", "segment_p2_p3_m", "segment_p3_p1_m",
    "waypoint_separation_m", "min_waypoint_separation_m",
    "repeated_edge_ratio", "waypoint_angle_diff_deg", "segment_balance_ratio",
    "prune_branch_length_m", "prune_clean_branch_length_m",
)
_OPTIONAL_BOOL_KEYS = ("feasible", "is_degenerate_loop")
_OPTIONAL_STR_KEYS = ("selection_status", "alns_operator_stats")

# overlap_ratio / repeated_edge_ratio는 build_result_row가 별도 규칙으로 채우므로 제외한다.
_PASSTHROUGH_KEYS = tuple(
    key
    for key in (*_OPTIONAL_INT_KEYS, *_OPTIONAL_FLOAT_KEYS, *_OPTIONAL_BOOL_KEYS, *_OPTIONAL_STR_KEYS)
    if key not in ("overlap_ratio", "repeated_edge_ratio")
)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# ---------------------------------------------------------------------------
# 하네스 독립 계산 — 최종 경로(paths[0])와 graph만 본다
# ---------------------------------------------------------------------------

def route_distance_km(graph, paths) -> Optional[float]:
    """paths를 따라 graph의 edge 'length'(미터)를 합산해 km로 반환한다.

    solver 자기 신고를 믿지 않고 그래프 위에서 독립적으로 재계산한다 — solver가 실제로
    그래프를 따라가는 타당한 경로를 반환했는지와 무관하게 객관적인 거리를 얻기 위함.
    단위는 src/route_engine/engines/circular_rcsp.py의 total_m / 1000 관례를 따른다.

    graph에 접근할 수 없거나(None) edge에 'length'가 없으면 None을 반환한다 — solve()
    자체는 성공했으므로 이 부가 지표 계산 실패로 전체를 실패 처리하지 않는다.
    """
    if graph is None or not paths:
        return None
    try:
        total_m = 0.0
        for path in paths:
            for u, v in zip(path, path[1:]):
                total_m += graph[u][v]["length"]
        return round(total_m / 1000, 4)
    except Exception:
        return None


def is_closed_loop(paths) -> Optional[bool]:
    """대표 경로(paths[0])의 시작 노드와 끝 노드가 같은지 — 순환이 실제로 닫혔는지의
    최소 기준."""
    if not paths or len(paths[0]) < 2:
        return None
    return paths[0][0] == paths[0][-1]


def count_spikes(paths) -> Optional[int]:
    """대표 경로에서 'A→B→A'처럼 갔다가 바로 되돌아오는 잔가시 개수.

    막다른 길을 갔다가 되돌아 나오는 구간은 사용자 산책 경로에서 실제로 자주 지적되는
    품질 문제라, 경로 모양을 정량화하는 게이트 지표 중 하나로 둔다.
    """
    if not paths or len(paths[0]) < 3:
        return 0
    primary = paths[0]
    return sum(1 for i in range(len(primary) - 2) if primary[i] == primary[i + 2])


def path_repeated_edge_ratio(graph, paths) -> Optional[float]:
    """대표 경로의 재통행 거리 비율 — 엔진과 **같은** 거리 가중 정의로 재계산한다.

    2026-09-02에 엔진이 이 지표를 거리 가중 정의(waypoint_route_builder.edge_overlap_ratio
    — 구간의 두 번째 이후 통행분만 repeated에 가산)로 이행하고 퇴화 판정 임계값도
    0.50 → 0.35로 함께 재조정했는데, 하네스만 이행 전 정의(통행 횟수 기준
    reused/total)로 남아 있었다. 같은 단순 왕복 경로에서 거리 가중은 0.5, 횟수 기준은
    1.0이라, 두 값이 한 컬럼에 섞이면 0.35 임계값 판정이 무너진다.
    이제 엔진과 하네스가 같은 함수를 호출한다(2026-09-10).

    거리 가중이므로 graph가 반드시 필요하다. graph가 없거나 edge에 'length'가 없으면
    (MissingEdgeAttributeError) None — 진단 지표 하나 때문에 행 전체를 실패로 만들지 않는다.
    """
    if graph is None or not paths or len(paths[0]) < 2:
        return None
    try:
        return round(edge_overlap_ratio(graph, paths[0]), 4)
    except Exception:
        return None


def circularity_q(graph, paths, perimeter_m: Optional[float]) -> Optional[float]:
    """등주 지수(isoperimetric quotient) Q = 4π·A / P².

        A = 최종 경로가 그리는 폐곡선의 면적(m²)
        P = 그 경로의 총 길이(m)

    완전한 원이면 1.0, 찌그러질수록 0에 가까워지고, 단순 왕복(면적 0)이면 0.0이다.

    추가 이유(2026-09-10): 기존 원형성 지표(waypoint_separation_m, segment_balance_ratio)는
    전부 "선언한 경유지 분해"를 기준으로 계산돼, 그 대리 지표가 실제 원형성과 상관이
    있는지 검증할 기준값 자체가 없었다. 이 값은 최종 node_ids의 좌표만 쓰므로 경유지와
    완전히 무관하고, 추가 A* 호출도 없다.

    면적은 로컬 평면 근사(equirectangular: 경로 중심 위도에서 경도를 cos(lat0)으로 축소)
    후 신발끈 공식으로 구한다. 서울 규모(한 변 수 km)에서 이 근사 오차는 지표 용도에
    무시할 수준이다.

    한계: 자기 교차가 있는 경로는 신발끈이 부호 상쇄를 일으켜 면적을 과소평가한다.
    그런 경로는 이미 repeated_edge_ratio가 걸러내는 대상이지만, Q 값 하나만 보고
    "원형이 아니다"라고 단정하지 말 것.

    닫히지 않은 경로이거나 좌표(lat/lon)가 없는 노드가 있으면 None — 면적이 정의되지 않는다.
    """
    if graph is None or not paths or perimeter_m is None or perimeter_m <= 0:
        return None
    path = paths[0]
    if len(path) < 3 or path[0] != path[-1]:
        return None
    try:
        coords = [(graph.nodes[n]["lat"], graph.nodes[n]["lon"]) for n in path[:-1]]
    except KeyError:
        return None
    if len(coords) < 2:
        return None
    # 서로 다른 점이 2개뿐인 완전 왕복(A→B→A)은 신발끈이 자연히 0을 내어 Q=0.0이 된다.

    lat0 = sum(lat for lat, _ in coords) / len(coords)
    lon0 = sum(lon for _, lon in coords) / len(coords)
    cos_lat0 = math.cos(math.radians(lat0))
    xy = [
        (
            _EARTH_RADIUS_M * math.radians(lon - lon0) * cos_lat0,
            _EARTH_RADIUS_M * math.radians(lat - lat0),
        )
        for lat, lon in coords
    ]

    twice_area = 0.0
    for (x1, y1), (x2, y2) in zip(xy, xy[1:] + xy[:1]):
        twice_area += x1 * y2 - x2 * y1
    area_m2 = abs(twice_area) / 2

    return round(4 * math.pi * area_m2 / (perimeter_m ** 2), 4)


# ---------------------------------------------------------------------------
# 반환값 검증 / 행 생성
# ---------------------------------------------------------------------------

def validate_solver_result(result) -> dict:
    """solve() 반환값이 BasePathSolver 규격을 지키는지 검증한다.

    규격 위반은 알고리즘 버그로 간주해 예외를 던지고, 호출부가 다른 solver를 중단시키지
    않는 '실패' 행으로 변환한다.

    선택 필드는 _OPTIONAL_*_KEYS 표만 보고 검증한다 — 필드가 늘어날 때 if 블록을 하나씩
    복붙하던 구조가 컬럼 누락의 원인이었으므로 표 기반으로 바꿨다(2026-09-10).

    overlap_ratio 기본값 변경(2026-09-10): 예전에는 키가 없으면 0.0으로 채웠는데, 그
    탓에 이 지표를 아예 계산하지 않는 순환 solver의 행이 "겹침 0%"라는 실측값처럼
    보였다. 이제 없으면 None이다(편도 solver는 계속 실제 계산값을 보고한다).
    """
    if not isinstance(result, dict):
        raise TypeError(f"solve()는 dict를 반환해야 합니다 (실제 타입: {type(result).__name__})")

    missing = [key for key in REQUIRED_RESULT_KEYS if key not in result]
    if missing:
        raise ValueError(f"solve() 반환값에 필수 키 누락: {missing}")

    if not isinstance(result["paths"], list):
        raise TypeError(f"'paths'는 list여야 합니다 (실제 타입: {type(result['paths']).__name__})")
    if not _is_number(result["cost"]):
        raise TypeError(f"'cost'는 float(또는 int)여야 합니다 (실제 타입: {type(result['cost']).__name__})")

    validated = {"paths": result["paths"], "cost": result["cost"]}

    for key in _OPTIONAL_INT_KEYS:
        value = result.get(key)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
            raise TypeError(f"'{key}'는 int여야 합니다 (실제 타입: {type(value).__name__})")
        validated[key] = value

    for key in _OPTIONAL_FLOAT_KEYS:
        value = result.get(key)
        if value is not None and not _is_number(value):
            raise TypeError(f"'{key}'는 float(또는 int)여야 합니다 (실제 타입: {type(value).__name__})")
        validated[key] = value

    for key in _OPTIONAL_BOOL_KEYS:
        value = result.get(key)
        if value is not None and not isinstance(value, bool):
            raise TypeError(f"'{key}'는 bool이어야 합니다 (실제 타입: {type(value).__name__})")
        validated[key] = value

    for key in _OPTIONAL_STR_KEYS:
        value = result.get(key)
        if value is not None and not isinstance(value, str):
            raise TypeError(f"'{key}'는 str이어야 합니다 (실제 타입: {type(value).__name__})")
        validated[key] = value

    return validated


def evaluate_gate(row: dict, circular: Optional[bool]) -> tuple[Optional[bool], Optional[str]]:
    """최종 경로 관측값만으로 합격 여부를 판정한다(2026-09-10 신설).

    circular=False(편도)나 None(모름)이면 (None, None) — 이 게이트는 순환 경로 전용이다.
    편도 경로는 애초에 닫히면 안 되고, A*/Dijkstra처럼 target_km을 아예 고려하지 않는
    알고리즘도 섞여 있어 같은 기준을 적용하면 무의미한 판정이 된다.

    게이트에 넣지 않는 것과 그 이유:
      - feasible / selection_status : fallback은 "내부 제약을 만족하는 경유지 조합을
        못 찾았다"는 뜻일 뿐이며, 최종 경로가 기준을 만족하면 정상 해다.
      - is_degenerate_loop : 세 조건 중 둘(waypoint_separation_m, segment_balance_ratio)이
        선언 경유지 분해 기반이라 최종 경로 품질과 어긋날 수 있다
        (grasp_waypoint_common.compute_route_geometry_metrics 참고).
      - effective_waypoints_used 불일치 : 경유지 소실은 품질 미달이 아니라 N 튜닝의
        비용 효율 문제다.
      - circularity_q : 아직 임계값을 정할 실측이 없다. 대리 지표 검증(이슈 H)이
        끝난 뒤 편입 여부를 판단한다.
    """
    if not circular:
        return None, None

    failures = []
    if row.get("status") != "ok":
        failures.append("status")
        return False, ",".join(failures)  # 실패 행은 나머지 지표가 전부 비어 있다

    if row.get("is_closed_loop") is not True:
        failures.append("is_closed_loop")

    deviation = row.get("distance_deviation_km")
    if deviation is None or deviation > MAX_DISTANCE_DEVIATION_KM:
        failures.append("distance_deviation_km")

    repeated = row.get("repeated_edge_ratio")
    if repeated is None or repeated > MAX_REPEATED_EDGE_RATIO:
        failures.append("repeated_edge_ratio")

    spikes = row.get("spike_count")
    if spikes is None or spikes > MAX_SPIKE_COUNT:
        failures.append("spike_count")

    return (not failures), (",".join(failures) if failures else None)


def _empty_row() -> dict:
    """RESULT_COLUMNS 전부를 None으로 깐 행. 모든 행 생성이 여기서 출발하므로,
    컬럼을 추가해도 어떤 호출 경로에서든 키가 빠지지 않는다."""
    return {column: None for column in RESULT_COLUMNS}


def failed_row(solver, status: str, elapsed_sec: float, error: str, target_km=None,
               circular: Optional[bool] = None) -> dict:
    """예외·타임아웃·규격 위반 행. 품질 지표는 전부 None으로 남는다.

    circular를 주면 게이트가 매겨진다(순환 실행에서 실패는 곧 불합격).

    집계 시 주의: 실패 행의 품질 지표가 비어 있으므로, 품질 평균만 보면 어려운 조건에서
    실패하는 알고리즘일수록 좋아 보인다. 반드시 passed(게이트 통과율)와 함께 읽을 것.
    또 타임아웃 행의 elapsed_sec은 실제 소요가 아니라 제한시간에서 잘린(censored) 값이다.
    """
    row = _empty_row()
    row.update({
        "algorithm": getattr(solver, "name", solver),
        "status": status,
        "elapsed_sec": round(elapsed_sec, 6),
        "target_km": target_km,
        "error": error,
    })
    row["passed"], row["gate_failed_on"] = evaluate_gate(row, circular)
    return row


def build_result_row(solver, graph, params: dict, elapsed_sec: float, result: dict,
                     circular: Optional[bool] = None) -> dict:
    """검증을 통과한 solve() 결과를 표준 결과 행으로 만든다.

    benchmark.py::_run_single()과 러너 4종이 **모두** 이 함수를 쓴다 — 예전에는 각자
    dict 리터럴을 들고 있어서 컬럼이 늘 때마다 누락이 생겼다.

    circular(출발=도착 여부)를 주면 합격 게이트를 함께 매긴다. 안 주면 passed는 None이다.
    """
    target_km = params.get("target_km")
    time_budget_sec = params.get("time_budget_sec")
    paths = result["paths"]

    distance_km = route_distance_km(graph, paths)
    perimeter_m = distance_km * 1000 if distance_km is not None else None

    row = _empty_row()
    for key in _PASSTHROUGH_KEYS:
        row[key] = result.get(key)

    row.update({
        "algorithm": getattr(solver, "name", solver),
        "status": "ok",
        "elapsed_sec": round(elapsed_sec, 6),
        "within_time_budget": (elapsed_sec <= time_budget_sec) if time_budget_sec is not None else None,
        "distance_km": distance_km,
        "target_km": target_km,
        "distance_deviation_km": (
            round(abs(distance_km - target_km), 4)
            if distance_km is not None and target_km is not None else None
        ),
        "is_closed_loop": is_closed_loop(paths),
        "spike_count": count_spikes(paths),
        # 엔진이 최종 경로(pruning 이후)에서 계산해 준 값을 우선하고, 안 주는 solver만
        # 하네스가 재계산한 값으로 채운다. 두 경로의 정의가 이제 동일하다(거리 가중).
        "repeated_edge_ratio": (
            result.get("repeated_edge_ratio")
            if result.get("repeated_edge_ratio") is not None
            else path_repeated_edge_ratio(graph, paths)
        ),
        "circularity_q": circularity_q(graph, paths, perimeter_m),
        "cost": result["cost"],
        "overlap_ratio": result.get("overlap_ratio"),
        "error": "",
    })
    row["passed"], row["gate_failed_on"] = evaluate_gate(row, circular)
    return row


def run_solver_task(solver, graph, start_node, target_node, params: dict) -> dict:
    """solver 1회 실행 → 표준 결과 행. 프로세스 풀 기반 러너 4종이 공유하는 본체다.

    benchmark.py::_run_single()은 이 함수를 쓰지 않는다 — 그쪽은 타임아웃 하드킬을 위해
    solve()를 별도 OS 프로세스에서 돌려야 해서 실행 구조가 다르다. 다만 행을 만드는
    부분(build_result_row / failed_row)은 동일하게 공유한다.
    """
    target_km = params.get("target_km")
    circular = start_node == target_node  # 순환 경로는 출발=도착

    t0 = time.perf_counter()
    try:
        raw_result = solver.solve(graph, start_node, target_node, params)
    except Exception as e:
        return failed_row(solver, "failed", time.perf_counter() - t0, repr(e), target_km, circular)

    elapsed = time.perf_counter() - t0

    try:
        result = validate_solver_result(raw_result)
    except Exception as e:
        return failed_row(solver, "failed", elapsed, str(e), target_km, circular)

    return build_result_row(solver, graph, params, elapsed, result, circular)
