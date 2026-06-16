import networkx as nx

from src.route_engine.engines.path_utils import extract_coordinates


def _flat_edge_weight(u: int, v: int, data: dict) -> float:
    length = data.get("length", 1.0) or 1.0
    slope  = data.get("slope_score", 0.5) or 0.5
    return length * (2.0 - slope) ** 2


def flat_oneway_route(G: nx.Graph, start_node: int, end_node: int) -> dict:
    """slope_score 기반 평지 편도 경로. cost = length * (2 - slope)^2 로 Dijkstra."""
    try:
        path_nodes = nx.shortest_path(G, start_node, end_node, weight=_flat_edge_weight)
    except (nx.NetworkXNoPath, Exception) as e:
        print(f"[flat/oneway] 오류: {e}")
        return {"nodes": [], "coordinates": [], "total_distance_km": 0.0, "avg_slope_score": 0.0}

    total_dist   = 0.0
    slope_scores = []
    for i in range(len(path_nodes) - 1):
        d = G.get_edge_data(path_nodes[i], path_nodes[i + 1]) or {}
        total_dist += d.get("length", 0)
        slope_scores.append(d.get("slope_score", 0.5) or 0.5)

    return {
        "nodes":             path_nodes,
        "coordinates":       extract_coordinates(G, path_nodes),
        "total_distance_km": round(total_dist / 1000, 2),
        "avg_slope_score":   round(sum(slope_scores) / len(slope_scores), 4) if slope_scores else 0.0,
    }
