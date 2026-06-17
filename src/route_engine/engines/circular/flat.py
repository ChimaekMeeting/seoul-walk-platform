import math

import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.profiles import get_profile
from src.route_engine.schema import CircularRouteInput, FallbackReason, RouteOutput

FLAT_THRESHOLD = 0.7  # 평지 판정 경사 점수 기준


class CircularFlatEngine:
    def __init__(
        self,
        inp: CircularRouteInput,
        G: nx.Graph,
        profile_name: str = "flat"
    ):
        self._inp          = inp
        self._G            = G.copy()  # 원본 그래프 보호
        self._utils        = PathUtils(self._G)
        profile            = get_profile(profile_name)
        self._weights      = profile.weights
        self._blocked_tags = profile.blocked_tags

    def run(self) -> RouteOutput:
        """
        평지 진입 후 순환하고 출발지로 복귀하는 경로를 생성합니다.
        """
        start = self._utils.find_nearest_node(self._inp.start_lat, self._inp.start_lon)
        if start is None:
            return RouteOutput(
                status="FAILED",
                mode="circular_flat",
                coordinates=[],
                total_km=0.0,
                fallback_reason=FallbackReason.NO_NEAREST_START_NODE,  # 출발 노드 없음
            )

        entry = self._find_flat_entry(start)

        nodes = self._generate_route(start, entry)  # 순환 경로 생성
        if not nodes:
            return RouteOutput(
                status="FAILED",
                mode="circular_flat",
                coordinates=[],
                total_km=0.0,
                fallback_reason=FallbackReason.NO_PATH,  # 경로 없음
            )

        pruned  = self._utils.prune_dead_ends(nodes)
        coords  = self._utils.extract_coordinates(pruned)  # [lat, lon] 좌표 목록
        total_m = self._utils.calc_distance(pruned)        # 총 이동 거리(미터)
        return RouteOutput(
            status="SUCCESS" if coords else "FAILED",
            mode="circular_flat",
            coordinates=coords,
            total_km=round(total_m / 1000, 2),
            fallback_reason=None,
        )

    def _generate_route(self, start: int, entry: int) -> list[int]:
        """
        평지 기준 절반 거리 지점까지 왕복하는 순환 경로를 반환합니다.
        """
        try:
            mid      = self._find_mid(entry)                                              # 절반 거리 지점 노드
            path_out = nx.shortest_path(self._G, start, mid, weight=self._flat_cost)     # 출발→중간

            visited = {tuple(sorted([path_out[i], path_out[i + 1]])): True              # 기방문 엣지 집합
                       for i in range(len(path_out) - 1)}

            def back_cost(u, v, data):
                ek = tuple(sorted([u, v]))
                return self._flat_cost(u, v, data) * (10.0 if ek in visited else 1.0)  # 기방문 억제

            path_back = nx.shortest_path(self._G, mid, start, weight=back_cost)         # 중간→출발
            return path_out + path_back[1:]
        except Exception:
            return []

    def _find_flat_entry(self, start: int) -> int:
        """
        출발 노드에서 가장 가까운 평지 진입 노드를 반환합니다.
        """
        target_m   = (self._inp.target_km or 3.0) * 1000  # 목표 거리(미터)
        flat_nodes = {
            n
            for u, v, d in self._G.edges(data=True)
            if (d.get("slope_score") or 0) >= FLAT_THRESHOLD  # 평지 기준 이상인 엣지의 노드
            for n in (u, v)
        }

        if start in flat_nodes or not flat_nodes:  # 이미 평지이거나 평지 없으면 그대로 반환
            return start

        sx = self._G.nodes[start].get("lon", 0)  # 출발점 경도
        sy = self._G.nodes[start].get("lat", 0)  # 출발점 위도

        best, best_d = start, float("inf")
        for node in flat_nodes:
            nd = self._G.nodes[node]
            if "lon" not in nd or "lat" not in nd:
                continue
            d = math.sqrt((nd["lon"] - sx) ** 2 + (nd["lat"] - sy) ** 2) * 111000  # 유클리드 추정 거리
            if d < best_d and d < target_m * 2:  # 목표 거리 2배 이내 최근접 갱신
                best, best_d = node, d
        return best

    def _find_mid(self, entry: int) -> int:
        """
        entry 기준 목표 거리 절반 지점에 가장 가까운 노드를 반환합니다.
        """
        target_m = (self._inp.target_km or 3.0) * 1000 / 2                                       # 왕복 기준 절반 거리(미터)
        lengths  = nx.single_source_dijkstra_path_length(self._G, entry, weight="length")         # entry 기준 거리 맵
        return min((n for n in lengths if n != entry), key=lambda n: abs(lengths[n] - target_m))  # 절반 지점 노드

    def _flat_cost(self, u: int, v: int, data: dict) -> float:
        """
        평지 기준 엣지 비용을 반환합니다. 비평지 엣지는 50배 억제합니다.
        """
        length = data.get("length", 1.0) or 1.0
        slope  = data.get("slope_score", 0.5) or 0.5
        return length * (1.0 if slope >= FLAT_THRESHOLD else 50.0)  # 비평지 엣지 억제

    def _calc_avg_slope(self, nodes: list[int]) -> float:
        """
        경로의 평균 경사 점수를 반환합니다.
        """
        scores = [
            (self._G.get_edge_data(nodes[i], nodes[i + 1]) or {}).get("slope_score", 0.5) or 0.5
            for i in range(len(nodes) - 1)
        ]
        return round(sum(scores) / len(scores), 4) if scores else 0.0
