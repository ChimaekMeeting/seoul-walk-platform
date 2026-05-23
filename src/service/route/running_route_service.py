"""
런닝/다이어트 모드 경로 추천 서비스

하천변·공원 위주 코스를 순환(circular) / 편도(oneway) 로 나눠 반환합니다.

주요 함수
---------
get_circular_route(lat, lng, target_km, ...)  → 출발점 기준 루프 코스
get_oneway_route(lat, lng, end_lat, end_lng, ...) → 출발점 → 도착점 단방향 코스
"""

from __future__ import annotations

import time
from typing import Optional

import networkx as nx

from src.repository.course_repository import get_courses_near
from src.repository.graph_repository import load_graph_near
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

def _apply_running_weights(G: nx.Graph) -> nx.Graph:
    """
    런닝 모드 전용 엣지 가중치 적용.

    하천변·공원 path_type 엣지를 선호하도록 custom_score 를 낮춥니다.
    - path_type 이 'river' 또는 'park' 이면 가중치 보너스 ×2
    - safety_score, nature_score 를 균등하게 반영
    """
    PREFERRED_PATH_TYPES = {"river", "park", "bike_track", "trail"}

    for u, v, data in G.edges(data=True):
        length     = data.get("length", 1.0) or 1.0
        safety     = data.get("safety_score", 1.0) or 1.0
        nature     = data.get("nature_score", 1.0) or 1.0
        path_type  = data.get("path_type", "") or ""

        # 하천변·공원 경로 보너스
        type_bonus = 2.0 if path_type.lower() in PREFERRED_PATH_TYPES else 1.0

        # custom_score 낮을수록 알고리즘이 선호
        custom_score = length / ((safety * nature * type_bonus) + 1e-6)
        G[u][v]["custom_score"] = custom_score

    return G


def _build_result(
    G: nx.Graph,
    nodes: list,
    mode: str,
    matched_courses: list[dict],
) -> dict:
    """공통 응답 딕셔너리 생성"""
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
) -> dict:
    """
    출발점 기준 순환(루프) 런닝 코스를 반환합니다.

    1단계: DB에서 출발점 반경 내 순환 코스(하천변·공원) 조회
    2단계: 그래프 기반 random_walk 알고리즘으로 실제 경로 생성
    3단계: 두 결과를 합쳐 응답 반환

    Args:
        lat, lng    : 출발점 위경도
        target_km   : 목표 거리 (km, 기본 5km)
        radius_m    : DB 코스 검색 반경 (미터)
        G           : 미리 로드된 NetworkX 그래프 (없으면 DB에서 로드)

    Returns:
        {
            "mode": "circular_running",
            "coordinates": [[lat, lng], ...],
            "total_distance_km": float,
            "matched_courses": [...]   # 반경 내 추천 코스 목록
        }
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

    if G.number_of_nodes() == 0:
        return {
            "mode": "circular_running",
            "coordinates": [],
            "total_distance_km": 0.0,
            "matched_courses": matched_courses,
            "error": "해당 위치 주변에 경로 데이터가 없습니다.",
        }

    # ── 3. 좌표 없는 노드 제거 (KeyError 방지) ────────────────
    invalid_nodes = [n for n, d in G.nodes(data=True) if "x" not in d or "y" not in d]
    if invalid_nodes:
        G = G.copy()
        G.remove_nodes_from(invalid_nodes)
        print(f"[running/circular] 좌표 없는 노드 {len(invalid_nodes)}개 제거")

    if G.number_of_nodes() == 0:
        return {
            "mode": "circular_running",
            "coordinates": [],
            "total_distance_km": 0.0,
            "matched_courses": matched_courses,
            "error": "유효한 노드가 없습니다.",
        }

    # ── 4. 런닝 가중치 적용 ────────────────────────────────────
    G = _apply_running_weights(G)

    # ── 5. 순환 경로 생성 ──────────────────────────────────────
    t2 = time.time()
    start_node = find_nearest_node(G, lat, lng)
    raw = random_walk_route(G, start_node, target_km, weight="custom_score")
    print(f"[running/circular] 경로 생성 ({time.time()-t2:.2f}s)")

    result = _build_result(G, raw["nodes"], "circular_running", matched_courses)
    print(f"[running/circular] 총 소요 {time.time()-t0:.2f}s")
    return result


def get_oneway_route(
    start_lat: float,
    start_lng: float,
    end_lat: float,
    end_lng: float,
    target_km: Optional[float] = None,
    use_random: bool = True,
    radius_m: float = 5_000,
    G: Optional[nx.Graph] = None,
) -> dict:
    """
    출발점 → 도착점 편도 런닝 코스를 반환합니다.

    1단계: DB에서 출발점 반경 내 편도 코스(하천변·공원) 조회
    2단계: 그래프 기반 경로 알고리즘으로 실제 경로 생성
           - use_random=True  → oneway_random (우회 경로, 더 긴 거리)
           - use_random=False → dijkstra (최단 경로)
    3단계: 두 결과를 합쳐 응답 반환

    Args:
        start_lat, start_lng : 출발점 위경도
        end_lat, end_lng     : 도착점 위경도
        target_km            : 목표 거리 (km, use_random=True 일 때만 사용)
        use_random           : True=우회 경로, False=최단 경로
        radius_m             : DB 코스 검색 반경 (미터)
        G                    : 미리 로드된 NetworkX 그래프

    Returns:
        {
            "mode": "oneway_running_random" | "oneway_running_shortest",
            "coordinates": [[lat, lng], ...],
            "total_distance_km": float,
            "matched_courses": [...]
        }
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

    # ── 2. 그래프 로드 ─────────────────────────────────────────
    t1 = time.time()
    import math
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
        return {
            "mode": "oneway_running",
            "coordinates": [],
            "total_distance_km": 0.0,
            "matched_courses": matched_courses,
            "error": "해당 위치 주변에 경로 데이터가 없습니다.",
        }

    # ── 3. 좌표 없는 노드 제거 (KeyError 방지) ────────────────
    invalid_nodes = [n for n, d in G.nodes(data=True) if "x" not in d or "y" not in d]
    if invalid_nodes:
        G = G.copy()
        G.remove_nodes_from(invalid_nodes)
        print(f"[running/oneway] 좌표 없는 노드 {len(invalid_nodes)}개 제거")

    if G.number_of_nodes() == 0:
        return {
            "mode": "oneway_running",
            "coordinates": [],
            "total_distance_km": 0.0,
            "matched_courses": matched_courses,
            "error": "유효한 노드가 없습니다.",
        }

    # ── 4. 런닝 가중치 적용 ────────────────────────────────────
    G = _apply_running_weights(G)

    # ── 4. 편도 경로 생성 ──────────────────────────────────────
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
    return result
