# src/service/route_service.py
import networkx as nx
from src.repository.graph_repository import load_graph_near
from src.service.path_finder import *

# ─────────────────────────────────────────
# Intent → 가중치 조정
# ─────────────────────────────────────────

def apply_intent_weights(G: nx.Graph, weights: dict) -> nx.Graph:
    """
    weights 딕셔너리의 레이어 가중치를 적용해 엣지에 대한 custom_score를 생성

    가중치 공식:
        custom_score = length / (safety_score^a * nature_score^b)
        → custom_score 낮을수록 알고리즘이 선호하는 엣지

    Args:
        G: NetworkX 그래프
        weights: {"safety": float, "nature": float}

    Returns:
        G: custom_score가 추가된 NetworkX 그래프
    """
    safety_w = weights.get("safety", 1.0)
    nature_w  = weights.get("nature", 1.0)

    for u, v, data in G.edges(data=True):
        length = data.get("length", 1.0) or 1.0
        safety = data.get("safety_score", 1.0) or 1.0
        nature  = data.get("nature_score", 1.0) or 1.0

        # 점수 높을수록 선호 → 분모에 올려서 custom_score 낮춤
        custom_score = length / ((safety ** safety_w) * (nature ** nature_w) + 1e-6)
        G[u][v]["custom_score"] = custom_score

    return G


# ─────────────────────────────────────────
# 메인 서비스 함수
# ─────────────────────────────────────────

def get_route(context: dict, weights: dict) -> dict:
    """
    경로 추천 메인 함수 (app.py에서 호출)
    Args:
        context: {
            "is_circular": bool,
            "origin": {"place_name": str, "address": str, "coordinate": {"lat": float, "lon": float}},
            "destination": {"place_name": str, "address": str, "coordinate": {"lat": float, "lon": float}},
            "purpose": str
        }
        weights: {"safety": float, "nature": float}
    
    Returns:
        {
            "mode": "random_walk" | "dijkstra",
            "coordinates": [[lat, lng], ...],
            "total_distance_km": float
        }
    """
    start_lat = context["origin"]["coordinate"]["lat"]
    start_lng = context["origin"]["coordinate"]["lon"]
    is_circular = context.get("is_circular", True)
    distance_km = context.get("distance_km", 3.0)

    radius_m = distance_km * 1000 * 1.5  # 목표 거리의 1.5배 반경으로 그래프 로드

    # 1. DB에서 그래프 로드
    G = load_graph_near(start_lat, start_lng, radius_m=radius_m)
    if G.number_of_nodes() == 0:
        return {"mode": None, "coordinates": [], "total_distance_km": 0.0, "error": "경로 데이터 없음"}

    # 2. 가중치 조정
    G = apply_intent_weights(G, weights)

    # 3. 알고리즘 분기
    intent = {"weight": "custom_score", "distance_km": distance_km}
    start_node = find_nearest_node(G, start_lat, start_lng)


    if is_circular:
        result = random_walk_route(G, start_node, distance_km, weight="custom_score")
        result["mode"] = "random_walk"
    else:
        end_lat = context["destination"]["coordinate"]["lat"]
        end_lng = context["destination"]["coordinate"]["lon"]
        end_node = find_nearest_node(G, end_lat, end_lng)
        result = dijkstra_route(G, start_node, end_node, weight="custom_score")
        result["mode"] = "dijkstra"
    
    
    print(f"결과: {result}")

    return result