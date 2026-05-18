# src/service/route_service.py
import networkx as nx
from src.repository.graph_repository import load_graph_near
from src.service.route.path_utils import find_nearest_node, extract_coordinates, prune_dead_ends
from src.service.route.path_circular_random import random_walk_route
from src.service.route.path_oneway_dijkstra import dijkstra_route
from src.service.route.path_oneway_random import oneway_random_route
import time

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



def get_route(context: dict, weights: dict, G_full: nx.Graph = None) -> dict:
    """
    경로 추천 메인 함수 (app.py에서 호출)
    Args:
        context: {
            "is_circular": bool,
            "distance_km" : float,
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

    # 0. 매개변수 추출
    mode = context.get("mode", "circular")
    start_lat = context["origin"]["coordinate"]["lat"]
    start_lng = context["origin"]["coordinate"]["lon"]
    distance_km = context.get("distance_km", 3.0)

    radius_m = distance_km * 1000 * 3.0
    t0 = time.time()

    # 1. DB에서 그래프 로드
    if G_full is not None:
         # 메모리에서 반경 필터링
        G = extract_subgraph_near(G_full, start_lat, start_lng, radius_m)
    else:
        G = load_graph_near(start_lat, start_lng, radius_m=radius_m)

    print(f"[1] load_graph_near: {time.time()-t0:.2f}s")
    t1 = time.time()

    if G.number_of_nodes() == 0:
        return {"mode": mode, "coordinates": [], "total_distance_km": 0.0, "error": "경로 데이터 없음"}

    # 2. 가중치 조정
    G = apply_intent_weights(G, weights)
    print(f"[2] apply_intent_weights: {time.time()-t1:.2f}s") # 프린트 유지
    t2 = time.time()

    # 3. 알고리즘 분기
    start_node = find_nearest_node(G, start_lat, start_lng)

    if mode == "circular":
        result = random_walk_route(G, start_node, distance_km, weight="custom_score")
        result["mode"] = "random_walk"
    elif mode in ["oneway_random", "oneway_shortest"]:
        if not context.get("destination"):
            return {"mode": mode, "coordinates": [], "total_distance_km": 0.0, "error": "편도 모드에서는 목적지가 필요합니다"}
        end_lat = context["destination"]["coordinate"]["lat"]
        end_lng = context["destination"]["coordinate"]["lon"]
        end_node = find_nearest_node(G, end_lat, end_lng)
        if mode == "oneway_random":
            result = oneway_random_route(G, start_node, end_node, distance_km, weight="custom_score")
            result["mode"] = "oneway_random"
        else:
            result = dijkstra_route(G, start_node, end_node, weight="custom_score")
            result["mode"] = "dijkstra"

    print(f"[3] route algorithm: {time.time()-t2:.2f}s")
    t3 = time.time()
    
    # 4. 가지치기 후처리
    pruned_nodes = prune_dead_ends(result["nodes"], G, max_branch_length=100)
    result["nodes"] = pruned_nodes
    result["coordinates"] = extract_coordinates(G, pruned_nodes)
    
    print(f"[4] prune+extract: {time.time()-t3:.2f}s") 
    print(f"[total] {time.time()-t0:.2f}s") 

    return result

def extract_subgraph_near(G: nx.Graph, lat: float, lng: float, radius_m: float) -> nx.Graph:
    import math

    # 위도 1도 ≈ 111km
    deg = radius_m / 111000
    nodes = [
        n for n, d in G.nodes(data=True)
        if "y" in d and "x" in d
        and abs(d["y"] - lat) <= deg 
        and abs(d["x"] - lng) <= deg * 1.3
    ]
    return G.subgraph(nodes).copy()
