"""
런닝/다이어트 모드 경로 추천 서비스

하천변·공원 위주 코스를 순환(circular) / 편도(oneway) 로 나눠 반환합니다.

주요 함수
---------
get_circular_route(lat, lng, target_km, ...)  → 출발점 기준 루프 코스
get_oneway_route(lat, lng, end_lat, end_lng, ...) → 출발점 → 도착점 단방향 코스
"""

from __future__ import annotations

import math
import time
from typing import Optional

import networkx as nx

from src.repository.route.course_repository import get_courses_near
from src.repository.route.graph_repository import load_graph_near
from src.schema.running_schema import (
    CircularRunningResponse,
    CourseInfo,
    OnewayRunningResponse,
)
from src.service.route.path_circular_random import random_walk_route
from src.service.route.path_oneway_dijkstra import dijkstra_route
from src.service.route.path_oneway_random import oneway_random_route
from src.service.route.path_utils import (
    extract_coordinates,
    find_nearest_node,
    prune_dead_ends,
)

# 런닝 모드에서 선호하는 코스 유형
RUNNING_COURSE_TYPES = ["river", "park", "bike_track", "trail"]

# 런닝 모드 기본 태그 필터
RUNNING_TAGS = ["런닝"]


# ──────────────────────────────────────────────────────────────
# 내부 헬퍼
# ──────────────────────────────────────────────────────────────

def _apply_running_weights(
    G: nx.Graph,
    slope_weight: float = 1.0,
    type_bonus: float = 2.0,
) -> nx.Graph:
    """
    런닝 모드 전용 ``custom_score``를 각 엣지에 세팅합니다.

    ``circular_running_route`` / ``oneway_running_route`` 호출 전에
    반드시 먼저 실행해야 합니다. 그래프를 in-place로 수정하고 반환합니다.

    가중치 공식::

        slope_factor        = 1.0 + slope_score * slope_weight
        effective_type_bonus = type_bonus  (river/park/bike_track/trail)
                             | 1.0         (일반 엣지)
        length_bonus        = 1.0 + log1p(length / 50.0)

        custom_score = (length * slope_factor)
                       / (safety * nature * effective_type_bonus * length_bonus + 1e-6)

    ``custom_score``가 낮을수록 경로 탐색 알고리즘이 선호합니다.

    Args:
        G            (nx.Graph) : 엣지에 ``length``, ``safety_score``, ``nature_score``,
                                  ``slope_score``, ``path_type`` 속성이 있는 그래프.
        slope_weight (float)    : 평지 선호도. 높을수록 경사 엣지 페널티 강화.
                                  범위 권장: 1.0 ~ 3.0. 기본값 1.0.
        type_bonus   (float)    : 공원·하천 선호도. river / park / bike_track / trail
                                  path_type 엣지에 적용되는 분모 배수.
                                  범위 권장: 1.0 ~ 3.0. 기본값 2.0.

    Returns:
        nx.Graph: ``custom_score``가 추가된 그래프 (입력 G와 동일 객체).
    """
    PREFERRED_PATH_TYPES = {"river", "park", "bike_track", "trail"}

    for u, v, data in G.edges(data=True):
        length      = data.get("length", 1.0) or 1.0
        safety      = data.get("safety_score", 1.0) or 1.0
        nature      = data.get("nature_score", 1.0) or 1.0
        slope       = data.get("slope_score", 0.0) or 0.0
        path_type   = data.get("path_type", "") or ""

        # 하천·공원·자전거도로 보너스 (파라미터로 제어)
        effective_type_bonus = type_bonus if path_type.lower() in PREFERRED_PATH_TYPES else 1.0

        # 경사 패널티: slope_weight로 강도 조절
        slope_factor = 1.0 + slope * slope_weight

        # 길이 보너스: 긴 엣지일수록 분모 증가 → 짧은 골목 회피
        length_bonus = 1.0 + math.log1p(length / 50.0)

        custom_score = (length * slope_factor) / (safety * nature * effective_type_bonus * length_bonus + 1e-6)
        G[u][v]["custom_score"] = custom_score

    return G


def _build_result(
    G: nx.Graph,
    nodes: list,
    mode: str,
    matched_courses: list[dict],
) -> dict:
    """
    경로 노드 목록을 응답 딕셔너리로 변환합니다.

    dead-end 가지치기(max_branch_length=300m) → 좌표 추출 → 총 거리 계산 순으로 처리합니다.

    Args:
        G               (nx.Graph)   : 경로 생성에 사용된 그래프.
        nodes           (list[int])  : 경로 노드 ID 목록.
        mode            (str)        : 응답에 포함할 모드 문자열.
                                       예: ``"circular_running"``, ``"oneway_running_random"``
        matched_courses (list[dict]) : DB에서 조회된 추천 코스 목록 (그대로 전달).

    Returns:
        dict: 아래 키를 포함하는 딕셔너리.

        - ``mode``              (str)        : 입력 ``mode`` 값.
        - ``coordinates``       (list)       : ``[[lat, lng], ...]`` 형태의 좌표 목록.
        - ``total_distance_km`` (float)      : 가지치기 후 경로의 총 거리 (km).
        - ``matched_courses``   (list[dict]) : 입력 ``matched_courses`` 값.
    """
    pruned = prune_dead_ends(nodes, G, max_branch_length=300)
    coords = extract_coordinates(G, pruned)
    total_m = sum(
        (G.get_edge_data(pruned[i], pruned[i + 1]) or {}).get("length", 0)
        for i in range(len(pruned) - 1)
    )
    return {
        "mode":               mode,
        "coordinates":        coords,
        "total_distance_km":  round(total_m / 1000, 2),
        "matched_courses":    matched_courses,  # DB에서 찾은 추천 코스 목록
    }


# ──────────────────────────────────────────────────────────────
# 공개 API
# ──────────────────────────────────────────────────────────────

def get_circular_route(
    lat: float,
    lng: float,
    target_km: float = 5.0,
    radius_m: float = 5_000,
    G: Optional[nx.Graph] = None,
) -> CircularRunningResponse:
    """
    출발점 기준 순환(루프) 런닝 코스를 반환합니다. (**자체 완결형**)

    그래프 로드·가중치 적용·경로 생성을 모두 내부에서 처리합니다.
    ``circular_running_route()``와 달리 외부에서 G를 준비하거나
    ``_apply_running_weights()``를 호출할 필요가 없습니다.

    Args:
        lat       (float)              : 출발점 위도.
        lng       (float)              : 출발점 경도.
        target_km (float)              : 목표 거리 (km). 기본값 5.0.
        radius_m  (float)              : DB 코스 검색 반경 (미터). 기본값 5,000.
        G         (nx.Graph, optional) : 미리 로드된 그래프. ``None``이면 DB에서 로드.

    Returns:
        dict: 아래 키를 포함하는 딕셔너리.

        - ``mode``              (str)        : ``"circular_running"``
        - ``coordinates``       (list)       : ``[[lat, lng], ...]`` 형태의 좌표 목록.
        - ``total_distance_km`` (float)      : 총 거리 (km).
        - ``matched_courses``   (list[dict]) : 반경 내 DB 추천 코스 목록.
        - ``error``             (str)        : 경로 생성 실패 시에만 포함.
    """
    t0 = time.time()

    # ── 1. DB 코스 조회 ────────────────────────────────────────
    matched_courses = get_courses_near(
        lat=lat,
        lng=lng,
        radius_m=radius_m,
        is_circular=True,
        course_types=RUNNING_COURSE_TYPES,
        tags=RUNNING_TAGS,
        limit=5,
    )
    print(f"[running/circular] DB 코스 {len(matched_courses)}건 조회 ({time.time()-t0:.2f}s)")

    # ── 2. 그래프 로드 ─────────────────────────────────────────
    t1 = time.time()
    graph_radius = target_km * 1000 * 2.5  # 목표 거리의 2.5배 반경
    if G is None:
        G = load_graph_near(lat, lng, radius_m=graph_radius)
    print(f"[running/circular] 그래프 로드 ({time.time()-t1:.2f}s)")

    courses = [CourseInfo(**c) for c in matched_courses]

    if G.number_of_nodes() == 0:
        return CircularRunningResponse(
            mode="circular_running",
            coordinates=[],
            total_distance_km=0.0,
            matched_courses=courses,
            error="해당 위치 주변에 경로 데이터가 없습니다.",
        )

    # ── 3. 좌표 없는 노드 제거 (KeyError 방지) ────────────────
    invalid_nodes = [n for n, d in G.nodes(data=True) if "x" not in d or "y" not in d]
    if invalid_nodes:
        G = G.copy()
        G.remove_nodes_from(invalid_nodes)
        print(f"[running/circular] 좌표 없는 노드 {len(invalid_nodes)}개 제거")

    if G.number_of_nodes() == 0:
        return CircularRunningResponse(
            mode="circular_running",
            coordinates=[],
            total_distance_km=0.0,
            matched_courses=courses,
            error="유효한 노드가 없습니다.",
        )

    # ── 4. 런닝 가중치 적용 ────────────────────────────────────
    G = _apply_running_weights(G)

    # ── 5. 순환 경로 생성 ──────────────────────────────────────
    t2 = time.time()
    start_node = find_nearest_node(G, lat, lng)
    raw = random_walk_route(G, start_node, target_km, weight="custom_score")
    print(f"[running/circular] 경로 생성 ({time.time()-t2:.2f}s)")

    result = _build_result(G, raw["nodes"], "circular_running", matched_courses)
    print(f"[running/circular] 총 소요 {time.time()-t0:.2f}s")
    return CircularRunningResponse(
        mode=result["mode"],
        coordinates=result["coordinates"],
        total_distance_km=result["total_distance_km"],
        matched_courses=courses,
    )


def get_oneway_route(
    start_lat: float,
    start_lng: float,
    end_lat: float,
    end_lng: float,
    target_km: Optional[float] = None,
    use_random: bool = True,
    radius_m: float = 5_000,
    G: Optional[nx.Graph] = None,
) -> OnewayRunningResponse:
    """
    출발점 → 도착점 편도 런닝 코스를 반환합니다. (**자체 완결형**)

    그래프 로드·가중치 적용·경로 생성을 모두 내부에서 처리합니다.
    ``use_random`` 값에 따라 알고리즘이 분기됩니다.

    Args:
        start_lat  (float)              : 출발점 위도.
        start_lng  (float)              : 출발점 경도.
        end_lat    (float)              : 도착점 위도.
        end_lng    (float)              : 도착점 경도.
        target_km  (float, optional)    : 목표 거리 (km). ``use_random=True``일 때만 사용.
                                          ``None``이면 직선 거리 기반으로 자동 설정.
        use_random (bool)               : ``True`` → Edge Penalty 우회 경로 (oneway_random).
                                          ``False`` → Dijkstra 최단 경로.
        radius_m   (float)              : DB 코스 검색 반경 (미터). 기본값 5,000.
        G          (nx.Graph, optional) : 미리 로드된 그래프. ``None``이면 DB에서 로드.

    Returns:
        dict: 아래 키를 포함하는 딕셔너리.

        - ``mode``              (str)        : ``"oneway_running_random"`` 또는
                                               ``"oneway_running_shortest"``
        - ``coordinates``       (list)       : ``[[lat, lng], ...]`` 형태의 좌표 목록.
        - ``total_distance_km`` (float)      : 총 거리 (km).
        - ``matched_courses``   (list[dict]) : 반경 내 DB 추천 코스 목록.
        - ``error``             (str)        : 경로 생성 실패 시에만 포함.
    """
    t0 = time.time()

    # ── 1. DB 코스 조회 ────────────────────────────────────────
    matched_courses = get_courses_near(
        lat=start_lat,
        lng=start_lng,
        radius_m=radius_m,
        is_circular=False,
        course_types=RUNNING_COURSE_TYPES,
        tags=RUNNING_TAGS,
        limit=5,
    )
    print(f"[running/oneway] DB 코스 {len(matched_courses)}건 조회 ({time.time()-t0:.2f}s)")

    courses = [CourseInfo(**c) for c in matched_courses]

    # ── 2. 그래프 로드 ─────────────────────────────────────────
    t1 = time.time()
    straight_m = math.sqrt(
        (start_lat - end_lat) ** 2 + (start_lng - end_lng) ** 2
    ) * 111_000  # 위도 1도 ≈ 111km
    graph_radius = max(straight_m * 1.5, 3_000)  # 직선 거리의 1.5배, 최소 3km

    if G is None:
        # 출발·도착 중간 지점 기준으로 로드
        mid_lat = (start_lat + end_lat) / 2
        mid_lng = (start_lng + end_lng) / 2
        G = load_graph_near(mid_lat, mid_lng, radius_m=graph_radius)
    print(f"[running/oneway] 그래프 로드 ({time.time()-t1:.2f}s)")

    if G.number_of_nodes() == 0:
        return OnewayRunningResponse(
            mode="oneway_running",
            coordinates=[],
            total_distance_km=0.0,
            matched_courses=courses,
            error="해당 위치 주변에 경로 데이터가 없습니다.",
        )

    # ── 3. 좌표 없는 노드 제거 (KeyError 방지) ────────────────
    invalid_nodes = [n for n, d in G.nodes(data=True) if "x" not in d or "y" not in d]
    if invalid_nodes:
        G = G.copy()
        G.remove_nodes_from(invalid_nodes)
        print(f"[running/oneway] 좌표 없는 노드 {len(invalid_nodes)}개 제거")

    if G.number_of_nodes() == 0:
        return OnewayRunningResponse(
            mode="oneway_running",
            coordinates=[],
            total_distance_km=0.0,
            matched_courses=courses,
            error="유효한 노드가 없습니다.",
        )

    # ── 4. 런닝 가중치 적용 ────────────────────────────────────
    G = _apply_running_weights(G)

    # ── 5. 편도 경로 생성 ──────────────────────────────────────
    t2 = time.time()
    start_node = find_nearest_node(G, start_lat, start_lng)
    end_node   = find_nearest_node(G, end_lat, end_lng)

    if use_random and target_km:
        raw = oneway_random_route(G, start_node, end_node, target_km, weight="custom_score")
        mode_label = "oneway_running_random"
    else:
        raw = dijkstra_route(G, start_node, end_node, weight="custom_score")
        mode_label = "oneway_running_shortest"

    print(f"[running/oneway] 경로 생성 ({time.time()-t2:.2f}s)")

    result = _build_result(G, raw["nodes"], mode_label, matched_courses)
    print(f"[running/oneway] 총 소요 {time.time()-t0:.2f}s")
    return OnewayRunningResponse(
        mode=result["mode"],
        coordinates=result["coordinates"],
        total_distance_km=result["total_distance_km"],
        matched_courses=courses,
    )
