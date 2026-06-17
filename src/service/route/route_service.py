import time

import networkx as nx

from src.repository.network.graph_repository import GraphRepository
from src.route_engine.engines.circular.random import CircularRandomEngine
from src.route_engine.engines.oneway.dijkstra import OnewayDijkstraEngine
from src.route_engine.engines.oneway.random import OnewayRandomEngine
from src.route_engine.schema import CircularRouteInput, OnewayRouteInput


class RouteService:
    def extract_subgraph_near(self, G: nx.Graph, lat: float, lon: float, radius_m: float) -> nx.Graph:
        """
        전체 그래프에서 주어진 좌표 반경 내 노드만 추출해 서브그래프를 반환합니다.
        """
        deg   = radius_m / 111000
        nodes = [
            n for n, d in G.nodes(data=True)
            if "lat" in d and "lon" in d
            and abs(d["lat"] - lat) <= deg
            and abs(d["lon"] - lon) <= deg * 1.3
        ]
        return G.subgraph(nodes).copy()

    def get_route(
        self,
        context: dict,
        profile_name: str = "default",
        G_full: nx.Graph = None,
    ) -> dict:
        """
        경로 추천 메인 함수.

        Args:
            context: {
                "mode": str,
                "distance_km": float,
                "origin": {"coordinate": {"lat": float, "lon": float}},
                "destination": {"coordinate": {"lat": float, "lon": float}},
            }
            profile_name: 경로 프로필 이름 (profiles.py 참고)
            G_full: 사전 로드된 전체 그래프 (없으면 DB에서 로드)

        Returns:
            {"mode": str, "coordinates": list, "total_distance_km": float, "error": str | None}
        """
        mode        = context.get("mode", "circular")
        start_lat   = context["origin"]["coordinate"]["lat"]
        start_lon   = context["origin"]["coordinate"]["lon"]
        distance_km = context.get("distance_km", 3.0)
        radius_m    = distance_km * 1000 * 3.0

        t0 = time.time()

        # 1. 그래프 로드
        if G_full is not None:
            G = self.extract_subgraph_near(G_full, start_lat, start_lon, radius_m)
        else:
            G = GraphRepository.load_graph_near(start_lat, start_lon, radius_m=radius_m)

        print(f"[1] load_graph_near: {time.time()-t0:.2f}s")

        if G.number_of_nodes() == 0:
            return {"mode": mode, "coordinates": [], "total_distance_km": 0.0, "error": "경로 데이터 없음"}

        # 2. 엔진 선택 및 실행
        t1 = time.time()

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
            return {"mode": mode, "coordinates": [], "total_distance_km": 0.0,
                    "error": f"알 수 없는 모드: {mode}"}

        output = engine.run()
        print(f"[2] route engine: {time.time()-t1:.2f}s")
        print(f"[total] {time.time()-t0:.2f}s")

        return {
            "mode":             output.mode,
            "coordinates":      output.coordinates,
            "total_distance_km": output.total_km,
            "error":            output.fallback_reason.value if output.fallback_reason else None,
        }
