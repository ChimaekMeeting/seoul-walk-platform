import networkx as nx

from src.route_engine.engines.path_utils import extract_coordinates


def dijkstra_route(
    G: nx.Graph,
    start_node: int,
    end_node: int,
    weight: str = "length"
) -> dict:
    try:
        path_nodes = nx.shortest_path(G, start_node, end_node, weight=weight)
        total_distance = sum(
            (G.get_edge_data(path_nodes[i], path_nodes[i+1]) or {}).get("length", 0)
            for i in range(len(path_nodes) - 1)
        )
        return {
            "nodes": path_nodes,
            "coordinates": extract_coordinates(G, path_nodes),
            "total_distance_km": round(total_distance / 1000, 2)
        }
    except nx.NetworkXNoPath:
        print(f"경로 없음: {start_node} → {end_node}")
        return {"nodes": [], "coordinates": [], "total_distance_km": 0.0}
    except Exception as e:
        print(f"오류: {e}")
        return {"nodes": [], "coordinates": [], "total_distance_km": 0.0}
