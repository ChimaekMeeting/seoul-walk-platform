import networkx as nx
from src.service.route.path_utils import extract_coordinates

def landmark_oneway_route(
    G: nx.Graph,
    start_node: int,
    end_node: int,
    landmark_node: int,
    weight: str = "custom_score"
) -> dict:
    try:
        # 1. start → landmark
        path1 = nx.shortest_path(G, start_node, landmark_node, weight=weight)

        # 2. 구간 1 엣지에 페널티 (2구간에서 다른 길 유도)
        original_weights = {}
        for i in range(len(path1) - 1):
            u, v = path1[i], path1[i + 1]
            if G.has_edge(u, v):
                original_weights[(u, v)] = G[u][v][weight]
                G[u][v][weight] = original_weights[(u, v)] * 100

        # 3. landmark → end
        path2 = nx.shortest_path(G, landmark_node, end_node, weight=weight)

        # 4. 가중치 원복
        for (u, v), old_w in original_weights.items():
            G[u][v][weight] = old_w

        full_path = path1[:-1] + path2
        total_dist_m = sum(
            (G.get_edge_data(full_path[i], full_path[i + 1]) or {}).get("length", 0)
            for i in range(len(full_path) - 1)
        )

        return {
            "nodes": full_path,
            "coordinates": extract_coordinates(G, full_path),
            "total_distance_km": round(total_dist_m / 1000, 2)
        }

    except nx.NetworkXNoPath:
        print(f"경로 없음: {start_node} → {landmark_node} → {end_node}")
        return {"nodes": [], "coordinates": [], "total_distance_km": 0.0}
    except Exception as e:
        print(f"오류: {e}")
        return {"nodes": [], "coordinates": [], "total_distance_km": 0.0}
