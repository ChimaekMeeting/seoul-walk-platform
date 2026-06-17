import math
import time

import folium
import networkx as nx
import streamlit as st

from src.repository.network.graph_repository import GraphRepository
from src.route_engine.engines.circular.flat import CircularFlatEngine
from src.route_engine.engines.circular.random import CircularRandomEngine
from src.route_engine.engines.oneway.dijkstra import OnewayDijkstraEngine
from src.route_engine.engines.oneway.flat import OnewayFlatEngine
from src.route_engine.engines.oneway.random import OnewayRandomEngine
from src.route_engine.schema import CircularRouteInput, OnewayRouteInput
from src.route_engine.scoring.scoring_engine import calculate_custom_score

# ═════════════════════════════════════════════════════════
# 상수
# ═════════════════════════════════════════════════════════

CIRCULAR_MODES = ["circular", "random_walk", "flat_circular"]

FLAT_MODES = {
    "🦵 평지 순환 (경사 최소화)": "flat_circular",
    "🦵 평지 편도 (경사 최소화)": "flat_oneway",
}


# ═════════════════════════════════════════════════════════
# 일반 경로 (slope 가중치 반영)
# ═════════════════════════════════════════════════════════


def apply_intent_weights_v2(G: nx.Graph, weights: dict) -> nx.Graph:
    """
    slope_score 페널티 포함 custom_score 계산.
    """
    return calculate_custom_score(G, {"mode": "general", "weights": weights})


def get_route_v2(context: dict, profile_name: str = "default", G_full: nx.Graph = None) -> dict:
    """
    경로 추천.

    Args:
        context      : mode, distance_km, origin, destination, purpose
        profile_name : 경로 프로필 이름 (profiles.py 참고)
        G_full       : 사전 로드된 전체 그래프 (없으면 DB에서 로드)
    """
    mode        = context.get("mode", "circular")
    start_lat   = context["origin"]["coordinate"]["lat"]
    start_lon   = context["origin"]["coordinate"]["lon"]
    distance_km = context.get("distance_km", 3.0)
    radius_m    = distance_km * 1000 * 3.0

    t0 = time.time()

    if G_full is not None:
        G = _extract_subgraph_near(G_full, start_lat, start_lon, radius_m)
    else:
        G = GraphRepository.load_graph_near(start_lat, start_lon, radius_m=radius_m)

    print(f"[v2][1] load_graph: {time.time()-t0:.2f}s")

    if G.number_of_nodes() == 0:
        return {"mode": mode, "coordinates": [], "total_distance_km": 0.0, "error": "경로 데이터 없음"}

    if mode == "circular":
        inp    = CircularRouteInput(start_lat=start_lat, start_lon=start_lon, target_km=distance_km)
        engine = CircularRandomEngine(inp, G, profile_name)

    elif mode in ["oneway_random", "oneway_shortest"]:
        if not context.get("destination"):
            return {"mode": mode, "coordinates": [], "total_distance_km": 0.0,
                    "error": "편도 모드에서는 목적지가 필요합니다"}
        end_lat = context["destination"]["coordinate"]["lat"]
        end_lon = context["destination"]["coordinate"]["lon"]
        inp     = OnewayRouteInput(
            start_lat=start_lat, start_lon=start_lon,
            end_lat=end_lat,     end_lon=end_lon,
            target_km=distance_km,
        )
        engine = OnewayRandomEngine(inp, G, profile_name) if mode == "oneway_random" \
            else OnewayDijkstraEngine(inp, G, profile_name)

    else:
        return {"mode": mode, "coordinates": [], "total_distance_km": 0.0, "error": f"알 수 없는 모드: {mode}"}

    output = engine.run()
    print(f"[v2][total] {time.time()-t0:.2f}s")

    return {
        "mode":              output.mode,
        "coordinates":       output.coordinates,
        "total_distance_km": output.total_km,
        "error":             output.fallback_reason.value if output.fallback_reason else None,
    }


def _extract_subgraph_near(G: nx.Graph, lat: float, lon: float, radius_m: float) -> nx.Graph:
    deg   = radius_m / 111000
    nodes = [
        n for n, d in G.nodes(data=True)
        if "lat" in d and "lon" in d
        and abs(d["lat"] - lat) <= deg
        and abs(d["lon"] - lon) <= deg * 1.3
    ]
    return G.subgraph(nodes).copy()


# ═════════════════════════════════════════════════════════
# UI 헬퍼 (Streamlit 전용)
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
    """
    평지 경로 계산 + 세션 처리 + info 메시지 출력.
    """
    start_lat, start_lon = start

    st.session_state["flat_entry_coord"] = None

    if mode == "flat_oneway":
        if not end:
            st.error("평지 편도 모드는 도착지 설정이 필요합니다.")
            return None

        end_lat, end_lon = end
        half_dist = math.sqrt((end_lat - start_lat) ** 2 + (end_lon - start_lon) ** 2) * 111000
        radius_m  = max(half_dist * 1.5, distance_km * 1000 * 1.5)
        center_lat, center_lon = (start_lat + end_lat) / 2, (start_lon + end_lon) / 2
        G_near = _extract_subgraph_near(G, center_lat, center_lon, radius_m)

        inp    = OnewayRouteInput(
            start_lat=start_lat, start_lon=start_lon,
            end_lat=end_lat,     end_lon=end_lon,
        )
        engine = OnewayFlatEngine(inp, G_near, "flat")
        output = engine.run()
        result = {
            "mode":             "flat_oneway",
            "coordinates":      output.coordinates,
            "total_distance_km": output.total_km,
            "avg_slope_score":  engine.avg_slope_score,
        }

    else:  # flat_circular
        radius_m = distance_km * 1000 * 3.0
        G_near   = _extract_subgraph_near(G, start_lat, start_lon, radius_m)

        inp    = CircularRouteInput(start_lat=start_lat, start_lon=start_lon, target_km=distance_km)
        engine = CircularFlatEngine(inp, G_near, "flat")
        output = engine.run()
        result = {
            "mode":             "flat_circular",
            "coordinates":      output.coordinates,
            "total_distance_km": output.total_km,
            "avg_slope_score":  engine.avg_slope_score,
            "flat_entry_node":  engine.flat_entry_node,
        }

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
) -> None:
    """
    출발지↔경로시작, 경로끝↔도착지 점선 연결.
    """
    if not route_coordinates:
        return

    if start:
        route_start = route_coordinates[0]
        dist_m      = _dist_m(start, route_start)
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
        dist_m    = _dist_m(route_end, end)
        if dist_m > 10:
            _draw_dashed(m, route_end, end, f"경로 끝점 → 도착지 ({dist_m:.0f}m)")
            _draw_circle(m, route_end, "경로 끝점")


def _dist_m(a, b) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) * 111000


def _draw_dashed(m, a, b, tooltip):
    folium.PolyLine(
        locations=[a, b],
        color="#FF6B6B", weight=2, opacity=0.7,
        dash_array="8 6", tooltip=tooltip,
    ).add_to(m)


def _draw_circle(m, coord, tooltip):
    folium.CircleMarker(
        location=coord, radius=7,
        color="#FF6B6B", fill=True,
        fill_color="#FF6B6B", fill_opacity=0.9,
        tooltip=tooltip,
    ).add_to(m)
