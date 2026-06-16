"""
route_v2.py
────────────────────────────────────────────────────────
slope_score를 반영한 모든 경로 계산 로직을 통합한 모듈.
기존 route_service.py / flat_route.py / route_service_v2.py를
건드리지 않고 새로 작성.

제공 함수:
  [일반 경로] slope 가중치 포함
    - get_route_v2()              : 순환/편도 경로 (기존 get_route 대체)
    - apply_intent_weights_v2()   : slope 반영 가중치 계산

  [평지 전용] slope_score만 사용
    - flat_circular_route()       : 출발지 → 평지 진입 → 순환 → 복귀
    - flat_oneway_route()         : 출발지 → 목적지 평지 편도

  [UI 헬퍼] app_v2.py 전용
    - get_flat_mode_options()     : 사이드바 평지 모드 옵션
    - is_flat_mode()              : 평지 모드 여부
    - requires_destination()      : 목적지 필요 여부
    - get_mode_label()            : 순환/편도 레이블
    - run_flat_route()            : 평지 경로 계산 + 세션 처리
    - draw_route_connectors()     : 지도 점선 연결
"""

import math
import random
import time
import networkx as nx
import streamlit as st
import folium
from pydantic import BaseModel, Field

from src.repository.network.graph_repository import GraphRepository
from src.route_engine.engines.path_utils import (
    find_nearest_node,
    extract_coordinates,
    prune_dead_ends,
)
from src.route_engine.engines.circular.random import random_walk_route
from src.route_engine.engines.oneway.dijkstra import dijkstra_route
from src.route_engine.engines.oneway.random import oneway_random_route

# ═════════════════════════════════════════════════════════
# 상수
# ═════════════════════════════════════════════════════════

# 이 값 이상인 엣지를 "평지"로 판단
FLAT_THRESHOLD = 0.7

# 순환으로 분류되는 모드
CIRCULAR_MODES = ["circular", "random_walk", "flat_circular"]

# 사이드바 평지 모드 옵션
FLAT_MODES = {
    "🦵 평지 순환 (경사 최소화)": "flat_circular",
    "🦵 평지 편도 (경사 최소화)": "flat_oneway",
}


# ═════════════════════════════════════════════════════════
# 스키마
# ═════════════════════════════════════════════════════════


class WeightsV2(BaseModel):
    """slope 가중치가 추가된 확장 버전."""

    safety: float = Field(0.5, ge=0.0, le=1.0, description="가로등/CCTV 안전 지수")
    nature: float = Field(0.5, ge=0.0, le=1.0, description="공원/가로수길 자연 지수")
    slope: float = Field(
        0.5, ge=0.0, le=1.0, description="경사 회피 지수 — 높을수록 평지 선호"
    )


# ═════════════════════════════════════════════════════════
# 일반 경로 (slope 가중치 반영)
# ═════════════════════════════════════════════════════════


def apply_intent_weights_v2(G: nx.Graph, weights: dict) -> nx.Graph:
    """
    slope_score 페널티 포함 custom_score 계산.

    공식:
        slope_penalty = (2.0 - slope_score) ^ slope_w
        custom_score  = (length * slope_penalty) / (safety^a * nature^b + ε)
    """
    safety_w = weights.get("safety", 1.0)
    nature_w = weights.get("nature", 1.0)
    slope_w = weights.get("slope", 1.0)

    for u, v, data in G.edges(data=True):
        length = data.get("length", 1.0) or 1.0
        safety = data.get("safety_score", 0.5)
        nature = data.get("nature_score", 0.5)
        slope = data.get("slope_score", 0.5)

        slope_penalty = (2.0 - slope) ** slope_w
        custom_score = (length * slope_penalty) / (
            (safety + 1e-6) ** safety_w * (nature + 1e-6) ** nature_w
        )
        G[u][v]["custom_score"] = custom_score

    return G


def get_route_v2(context: dict, weights: dict, G_full: nx.Graph = None) -> dict:
    """
    slope 반영 경로 추천. 기존 get_route()와 동일 인터페이스.

    Args:
        context : mode, distance_km, origin, destination, purpose
        weights : {"safety", "nature", "slope"}
        G_full  : 사전 로드된 전체 그래프 (없으면 DB에서 로드)
    """
    mode = context.get("mode", "circular")
    start_lat = context["origin"]["coordinate"]["lat"]
    start_lon = context["origin"]["coordinate"]["lon"]
    distance_km = context.get("distance_km", 3.0)
    radius_m = distance_km * 1000 * 3.0

    t0 = time.time()

    # 그래프 로드
    if G_full is not None:
        G = _extract_subgraph_near(G_full, start_lat, start_lon, radius_m)
    else:
        G = GraphRepository.load_graph_near(start_lat, start_lon, radius_m=radius_m)

    print(f"[v2][1] load_graph: {time.time()-t0:.2f}s")

    if G.number_of_nodes() == 0:
        return {
            "mode": mode,
            "coordinates": [],
            "total_distance_km": 0.0,
            "error": "경로 데이터 없음",
        }

    # 가중치 적용
    G = apply_intent_weights_v2(G, weights)
    start_node = find_nearest_node(G, start_lat, start_lon)

    # 알고리즘 분기
    if mode == "circular":
        result = random_walk_route(G, start_node, distance_km, weight="custom_score")
        result["mode"] = "random_walk"

    elif mode in ["oneway_random", "oneway_shortest"]:
        if not context.get("destination"):
            return {
                "mode": mode,
                "coordinates": [],
                "total_distance_km": 0.0,
                "error": "편도 모드에서는 목적지가 필요합니다",
            }
        end_lat = context["destination"]["coordinate"]["lat"]
        end_lon = context["destination"]["coordinate"]["lon"]
        end_node = find_nearest_node(G, end_lat, end_lon)

        if mode == "oneway_random":
            result = oneway_random_route(
                G, start_node, end_node, distance_km, weight="custom_score"
            )
            result["mode"] = "oneway_random"
        else:
            result = dijkstra_route(G, start_node, end_node, weight="custom_score")
            result["mode"] = "dijkstra"
    else:
        return {
            "mode": mode,
            "coordinates": [],
            "total_distance_km": 0.0,
            "error": f"알 수 없는 모드: {mode}",
        }

    # 후처리
    pruned = prune_dead_ends(result["nodes"], G, max_branch_length=100)
    result["nodes"] = pruned
    result["coordinates"] = extract_coordinates(G, pruned)

    print(f"[v2][total] {time.time()-t0:.2f}s")
    return result


def _extract_subgraph_near(
    G: nx.Graph, lat: float, lon: float, radius_m: float
) -> nx.Graph:
    deg = radius_m / 111000
    nodes = [
        n
        for n, d in G.nodes(data=True)
        if "y" in d
        and "x" in d
        and abs(d["y"] - lat) <= deg
        and abs(d["x"] - lon) <= deg * 1.3
    ]
    return G.subgraph(nodes).copy()


# ═════════════════════════════════════════════════════════
# 평지 전용 경로
# ═════════════════════════════════════════════════════════


def _flat_edge_weight(u: int, v: int, data: dict) -> float:
    """평지 편도용 엣지 비용: cost = length * (2.0 - slope)^2"""
    length = data.get("length", 1.0) or 1.0
    slope = data.get("slope_score", 0.5) or 0.5
    return length * (2.0 - slope) ** 2


def _angle_to(G, a, b) -> float:
    dx = G.nodes[b].get("x", 0) - G.nodes[a].get("x", 0)
    dy = G.nodes[b].get("y", 0) - G.nodes[a].get("y", 0)
    return math.degrees(math.atan2(dx, dy)) % 360


def _angle_diff(a, b) -> float:
    d = abs(a - b) % 360
    return d if d <= 180 else 360 - d


def flat_circular_route(
    G: nx.Graph,
    start_node: int,
    target_distance_km: float = 3.0,
) -> dict:
    """
    출발지 → 평지 진입 → 평지 순환 → 출발지 복귀.

    Phase 1. 접근  : 출발지 → 가장 가까운 평지 노드 최단경로
    Phase 2. 순환  : 방향 유지 + 급경사 회피 원형 탐색
    Phase 3. 복귀  : 출발지까지 평지 우선 최단경로
    """
    target_m = target_distance_km * 1000
    path_nodes = [start_node]
    total_dist = 0.0
    sx = G.nodes[start_node].get("x", 0)
    sy = G.nodes[start_node].get("y", 0)

    # Phase 1: 평지 진입점 탐색
    flat_nodes = set()
    for u, v, d in G.edges(data=True):
        if (d.get("slope_score") or 0) >= FLAT_THRESHOLD:
            flat_nodes.add(u)
            flat_nodes.add(v)

    flat_entry = start_node
    if start_node not in flat_nodes and flat_nodes:
        min_dist = float("inf")
        for node in flat_nodes:
            nd = G.nodes[node]
            if "x" not in nd or "y" not in nd:
                continue
            d = math.sqrt((nd["x"] - sx) ** 2 + (nd["y"] - sy) ** 2) * 111000
            if d < min_dist and d < target_m * 2:
                min_dist = d
                flat_entry = node

    if flat_entry != start_node:
        try:
            approach = nx.shortest_path(G, start_node, flat_entry, weight="length")
            for n in approach[1:]:
                total_dist += (G.get_edge_data(path_nodes[-1], n) or {}).get(
                    "length", 0
                )
                path_nodes.append(n)
        except nx.NetworkXNoPath:
            flat_entry = start_node

    # Phase 2: 평지 순환
    approach_dist = total_dist
    loop_target = max(target_m - approach_dist * 2, target_m * 0.5)
    current = flat_entry
    visited_edges = {}
    loop_dist = 0.0
    heading = random.uniform(0, 360)

    while loop_dist < loop_target:
        neighbors = list(G.neighbors(current))
        if not neighbors:
            break

        probs = []
        for n in neighbors:
            edge_key = tuple(sorted([current, n]))
            edge_data = G.get_edge_data(current, n) or {}
            slope = edge_data.get("slope_score", 0.5) or 0.5
            visit_cnt = visited_edges.get(edge_key, 0)

            slope_w = slope if slope >= FLAT_THRESHOLD else 0.01
            ang = _angle_to(G, current, n)
            dir_score = max(0.01, 1.0 - _angle_diff(ang, heading) / 180.0)
            visit_pen = 1.0 / (1 + visit_cnt * 6)
            probs.append(slope_w * dir_score * visit_pen)

        total_p = sum(probs)
        if total_p == 0:
            break
        probs = [p / total_p for p in probs]

        next_node = random.choices(neighbors, weights=probs, k=1)[0]
        edge_key = tuple(sorted([current, next_node]))
        visited_edges[edge_key] = visited_edges.get(edge_key, 0) + 1

        step = (G.get_edge_data(current, next_node) or {}).get("length", 0)
        loop_dist += step
        total_dist += step
        path_nodes.append(next_node)
        current = next_node

        cur_ang = _angle_to(G, flat_entry, current)
        target_ang = (cur_ang + 90) % 360
        heading = (heading * 0.85 + target_ang * 0.15) % 360

    # Phase 3: 복귀
    if path_nodes[-1] != start_node:
        try:

            def return_weight(u, v, d):
                ek = tuple(sorted([u, v]))
                vc = visited_edges.get(ek, 0)
                return _flat_edge_weight(u, v, d) * (1 + vc * 2)

            return_path = nx.shortest_path(G, current, start_node, weight=return_weight)
            for n in return_path[1:]:
                total_dist += (G.get_edge_data(path_nodes[-1], n) or {}).get(
                    "length", 0
                )
                path_nodes.append(n)
        except nx.NetworkXNoPath:
            pass

    path_nodes = prune_dead_ends(path_nodes, G)
    slope_scores = [
        (G.get_edge_data(path_nodes[i], path_nodes[i + 1]) or {}).get(
            "slope_score", 0.5
        )
        or 0.5
        for i in range(len(path_nodes) - 1)
    ]
    avg_slope = round(sum(slope_scores) / len(slope_scores), 4) if slope_scores else 0.0

    return {
        "nodes": path_nodes,
        "coordinates": extract_coordinates(G, path_nodes),
        "total_distance_km": round(total_dist / 1000, 2),
        "avg_slope_score": avg_slope,
        "flat_entry_node": flat_entry,
    }


def flat_oneway_route(G: nx.Graph, start_node: int, end_node: int) -> dict:
    """
    slope_score 기반 평지 편도 경로.
    cost = length * (2.0 - slope_score)^2 로 Dijkstra.
    """
    try:
        path_nodes = nx.shortest_path(G, start_node, end_node, weight=_flat_edge_weight)
    except (nx.NetworkXNoPath, Exception) as e:
        print(f"[flat_oneway] 오류: {e}")
        return {
            "nodes": [],
            "coordinates": [],
            "total_distance_km": 0.0,
            "avg_slope_score": 0.0,
        }

    total_dist = 0.0
    slope_scores = []
    for i in range(len(path_nodes) - 1):
        d = G.get_edge_data(path_nodes[i], path_nodes[i + 1]) or {}
        total_dist += d.get("length", 0)
        slope_scores.append(d.get("slope_score", 0.5) or 0.5)

    return {
        "nodes": path_nodes,
        "coordinates": extract_coordinates(G, path_nodes),
        "total_distance_km": round(total_dist / 1000, 2),
        "avg_slope_score": (
            round(sum(slope_scores) / len(slope_scores), 4) if slope_scores else 0.0
        ),
    }


# ═════════════════════════════════════════════════════════
# UI 헬퍼 (app_v2.py 전용)
# ═════════════════════════════════════════════════════════


def get_flat_mode_options() -> dict:
    return FLAT_MODES


def is_flat_mode(mode: str) -> bool:
    return mode in FLAT_MODES.values()


def requires_destination(mode: str) -> bool:
    return mode in ["oneway_shortest", "oneway_random", "flat_oneway"]


def get_mode_label(mode: str) -> str:
    return "순환 🔄" if mode in CIRCULAR_MODES else "편도 ➡️"


def run_flat_route(
    G: nx.Graph,
    mode: str,
    start: list,
    end: list | None,
    distance_km: float,
) -> dict | None:
    """평지 경로 계산 + 세션 처리 + info 메시지 출력."""
    start_lat, start_lon = start

    if mode == "flat_oneway" and end:
        end_lat, end_lon = end
        center_lat = (start_lat + end_lat) / 2
        center_lon = (start_lon + end_lon) / 2
        half_dist = (
            math.sqrt((end_lat - start_lat) ** 2 + (end_lon - start_lon) ** 2) * 111000
        )
        radius_m = max(half_dist * 1.5, distance_km * 1000 * 1.5)
        ref_lat, ref_lon = center_lat, center_lon
    else:
        radius_m = distance_km * 1000 * 3.0
        ref_lat, ref_lon = start_lat, start_lon

    deg = radius_m / 111000
    near_nodes = [
        n
        for n, d in G.nodes(data=True)
        if "y" in d
        and "x" in d
        and abs(d["y"] - ref_lat) <= deg
        and abs(d["x"] - ref_lon) <= deg * 1.3
    ]
    G_near = G.subgraph(near_nodes).copy()
    start_node = find_nearest_node(G_near, start_lat, start_lon)

    st.session_state["flat_entry_coord"] = None

    if mode == "flat_circular":
        result = flat_circular_route(G_near, start_node, distance_km)
        result["mode"] = "flat_circular"
    else:
        if not end:
            st.error("평지 편도 모드는 도착지 설정이 필요합니다.")
            return None
        end_lat, end_lon = end
        end_node = find_nearest_node(G_near, end_lat, end_lon)
        result = flat_oneway_route(G_near, start_node, end_node)
        result["mode"] = "flat_oneway"

    if not result.get("coordinates"):
        st.error("오류 발생: 평지 경로 데이터 없음")
        return None

    avg = result.get("avg_slope_score", 0)
    st.info(f"🦵 평지 경로 생성 완료 — 평탄도 점수: {avg:.2f} / 1.00")
    return result


def draw_route_connectors(
    m: folium.Map,
    start: list | None,
    end: list | None,
    route_coordinates: list,
):
    """출발지↔경로시작, 경로끝↔도착지 점선 연결."""
    if not route_coordinates:
        return

    if start:
        route_start = route_coordinates[0]
        dist_m = _dist_m(start, route_start)
        if dist_m > 10:
            _draw_dashed(m, start, route_start, f"출발지 → 경로 시작점 ({dist_m:.0f}m)")
            _draw_circle(m, route_start, "경로 시작점")
        if dist_m > 200:
            st.warning(
                f"⚠️ 출발지 주변에 도보 네트워크가 없어 {dist_m:.0f}m 떨어진 "
                "가장 가까운 길에서 경로를 시작했어요. 출발지를 도로 근처로 다시 설정해보세요."
            )

    if end:
        route_end = route_coordinates[-1]
        dist_m = _dist_m(route_end, end)
        if dist_m > 10:
            _draw_dashed(m, route_end, end, f"경로 끝점 → 도착지 ({dist_m:.0f}m)")
            _draw_circle(m, route_end, "경로 끝점")


def _dist_m(a, b) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) * 111000


def _draw_dashed(m, a, b, tooltip):
    folium.PolyLine(
        locations=[a, b],
        color="#FF6B6B",
        weight=2,
        opacity=0.7,
        dash_array="8 6",
        tooltip=tooltip,
    ).add_to(m)


def _draw_circle(m, coord, tooltip):
    folium.CircleMarker(
        location=coord,
        radius=7,
        color="#FF6B6B",
        fill=True,
        fill_color="#FF6B6B",
        fill_opacity=0.9,
        tooltip=tooltip,
    ).add_to(m)
