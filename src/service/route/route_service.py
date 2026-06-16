import networkx as nx
import time

from src.interfaces.schema.prewalk_schema import Weights
from src.repository.network.graph_repository import GraphRepository
from src.route_engine.engines.path_utils import find_nearest_node, extract_coordinates, prune_dead_ends
from src.route_engine.engines.circular.random import random_walk_route
from src.route_engine.engines.oneway.dijkstra import dijkstra_route
from src.route_engine.engines.oneway.random import oneway_random_route


class RouteService:
    def apply_intent_weights(self, G: nx.Graph, weights: Weights) -> nx.Graph:
        """
        Weights 스키마의 레이어 가중치를 적용해 엣지에 대한 custom_score를 생성

        가중치 공식:
            custom_score = length / (safety_score^a * nature_score^b)
            → custom_score 낮을수록 알고리즘이 선호하는 엣지

        Args:
            G: NetworkX 그래프
            weights: 레이어별 가중치 (0.0 ~ 1.0)

        Returns:
            G: custom_score가 추가된 NetworkX 그래프
        """
        safety_w = weights.safety
        nature_w = weights.nature

        for u, v, data in G.edges(data=True):
            length = data.get("length", 1.0) or 1.0
            safety = data.get("safety_score", 0.5)
            nature = data.get("nature_score", 0.5)

            # 점수 높을수록 선호 → 분모에 올려서 custom_score 낮춤
            custom_score = length / ((safety + 1e-6) ** safety_w * (nature + 1e-6) ** nature_w)
            G[u][v]["custom_score"] = custom_score

        return G

    def extract_subgraph_near(self, G: nx.Graph, lat: float, lon: float, radius_m: float) -> nx.Graph:
        """
        전체 그래프에서 주어진 좌표 반경 내 노드만 추출해 서브그래프를 반환합니다.
        """
        deg = radius_m / 111000
        nodes = [
            n for n, d in G.nodes(data=True)
            if "y" in d and "x" in d
            and abs(d["y"] - lat) <= deg
            and abs(d["x"] - lon) <= deg * 1.3
        ]
        return G.subgraph(nodes).copy()

    def get_route(self, context: dict, weights: Weights, G_full: nx.Graph = None) -> dict:
        """
        경로 추천 메인 함수
        Args:
            context: {
                "is_circular": bool,
                "distance_km" : float,
                "origin": {"place_name": str, "address": str, "coordinate": {"lat": float, "lon": float}},
                "destination": {"place_name": str, "address": str, "coordinate": {"lat": float, "lon": float}},
                "purpose": str
            }
            weights: 레이어별 가중치 (0.0 ~ 1.0)

        Returns:
            {
                "mode": "random_walk" | "dijkstra",
                "coordinates": [[lat, lon], ...],
                "total_distance_km": float
            }
        """
        # 0. 매개변수 추출
        mode        = context.get("mode", "circular")
        start_lat   = context["origin"]["coordinate"]["lat"]
        start_lon   = context["origin"]["coordinate"]["lon"]
        distance_km = context.get("distance_km", 3.0)

        radius_m = distance_km * 1000 * 3.0
        t0 = time.time()

        # 1. DB에서 그래프 로드
        if G_full is not None:
            G = self.extract_subgraph_near(G_full, start_lat, start_lon, radius_m)
        else:
            G = GraphRepository.load_graph_near(start_lat, start_lon, radius_m=radius_m)

        print(f"[1] load_graph_near: {time.time()-t0:.2f}s")
        t1 = time.time()

        if G.number_of_nodes() == 0:
            return {"mode": mode, "coordinates": [], "total_distance_km": 0.0, "error": "경로 데이터 없음"}

        # 2. 가중치 조정
        G = self.apply_intent_weights(G, weights)
        print(f"[2] apply_intent_weights: {time.time()-t1:.2f}s") # 프린트 유지
        t2 = time.time()

        # 3. 알고리즘 분기
        start_node = find_nearest_node(G, start_lat, start_lon)

        if mode == "circular":
            result = random_walk_route(G, start_node, distance_km, weight="custom_score")
            result["mode"] = "random_walk"
        elif mode in ["oneway_random", "oneway_shortest"]:
            if not context.get("destination"):
                return {"mode": mode, "coordinates": [], "total_distance_km": 0.0, "error": "편도 모드에서는 목적지가 필요합니다"}
            end_lat  = context["destination"]["coordinate"]["lat"]
            end_lon  = context["destination"]["coordinate"]["lon"]
            end_node = find_nearest_node(G, end_lat, end_lon)
            if mode == "oneway_random":
                result = oneway_random_route(G, start_node, end_node, distance_km, weight="custom_score")
                result["mode"] = "oneway_random"
            else:
                result = dijkstra_route(G, start_node, end_node, weight="custom_score")
                result["mode"] = "dijkstra"

        print(f"[3] route algorithm: {time.time()-t2:.2f}s")
        t3 = time.time()

        # 4. 가지치기 후처리
        pruned_nodes         = prune_dead_ends(result["nodes"], G, max_branch_length=100)
        result["nodes"]      = pruned_nodes
        result["coordinates"] = extract_coordinates(G, pruned_nodes)

        print(f"[4] prune+extract: {time.time()-t3:.2f}s")
        print(f"[total] {time.time()-t0:.2f}s")

        # 5. 경로 품질 지수 계산
        total_length = 0.0
        safety_sum   = 0.0
        nature_sum   = 0.0

        for i in range(len(pruned_nodes) - 1):
            u, v = pruned_nodes[i], pruned_nodes[i+1]
            if G.has_edge(u, v):
                data   = G[u][v]
                length = data.get("length", 0.0) or 0.0
                safety = data.get("safety_score", 0.5)
                nature = data.get("nature_score", 0.5)
                total_length += length
                safety_sum   += safety * length
                nature_sum   += nature * length

            if total_length > 0:
                safety_avg = safety_sum / total_length
                nature_avg = nature_sum / total_length
            else:
                safety_avg = 1.0
                nature_avg = 1.0

            result["safety_index"] = round(safety_avg * 10, 1)
            result["nature_index"] = round(nature_avg * 10, 1)

        return result
