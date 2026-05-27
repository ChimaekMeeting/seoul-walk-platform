# src/service/route/path_oneway_random.py
import networkx as nx
import math
import random
from src.route_engine.path_utils import extract_coordinates, find_nearest_node

def oneway_random_route(G: nx.Graph, start_node: int, end_node: int, target_distance_km: float, weight: str = "custom_score") -> dict:
    """
    중복 없는 편도 우회 모드:
    1구간에서 사용한 도로에 페널티를 주어 2구간에서 다른 길을 선택하도록 강제함
    """
    target_m = target_distance_km * 1000
    p1, p2 = G.nodes[start_node], G.nodes[end_node]
    
    # 1. 경유지 후보 탐색 (이전과 동일)
    candidates = []
    for node, data in G.nodes(data=True):
        if node in [start_node, end_node]: continue
        d1 = math.sqrt((data['x'] - p1['x'])**2 + (data['y'] - p1['y'])**2) * 111000
        d2 = math.sqrt((data['x'] - p2['x'])**2 + (data['y'] - p2['y'])**2) * 111000
        total_straight = d1 + d2
        if (target_m * 0.6) <= total_straight <= (target_m * 0.9):
            candidates.append((node, abs(total_straight - target_m * 0.8)))

    if not candidates:
        best_waypoint = find_nearest_node(G, (p1['y']+p2['y'])/2 + 0.005, (p1['x']+p2['x'])/2 + 0.005)
    else:
        candidates.sort(key=lambda x: x[1])
        best_waypoint = random.choice(candidates[:5])[0]

    try:
        # --- 핵심 로직 시작 ---
        
        # 2. 구간 1 계산 (Start -> Waypoint)
        path1 = nx.shortest_path(G, start_node, best_waypoint, weight=weight)
        
        # 3. 구간 1에서 사용한 엣지에 일시적 페널티 부여
        # 기존 가중치에 아주 큰 값을 곱해서 알고리즘이 피하게 만듭니다.
        original_weights = {}
        for i in range(len(path1) - 1):
            u, v = path1[i], path1[i+1]
            # 엣지 데이터 보관 및 페널티 부여
            if G.has_edge(u, v):
                original_weights[(u, v)] = G[u][v][weight]
                G[u][v][weight] = original_weights[(u, v)] * 100  # 100배 페널티
        
        # 4. 구간 2 계산 (Waypoint -> End) - 이제 1구간 길은 피해서 찾음
        path2 = nx.shortest_path(G, best_waypoint, end_node, weight=weight)
        
        # 5. 그래프 가중치 원복 (다음 요청을 위해 필수!)
        for (u, v), old_w in original_weights.items():
            G[u][v][weight] = old_w
            
        # --- 핵심 로직 끝 ---

        full_path = path1[:-1] + path2
        total_dist_m = sum(G.get_edge_data(full_path[i], full_path[i+1]).get("length", 0) for i in range(len(full_path)-1))

        return {
            "nodes": full_path,
            "coordinates": extract_coordinates(G, full_path),
            "total_distance_km": round(total_dist_m / 1000, 2),
            "mode": "oneway_random"
        }
    except:
        from src.route_engine.path_oneway_dijkstra import dijkstra_route
        return dijkstra_route(G, start_node, end_node, weight=weight)