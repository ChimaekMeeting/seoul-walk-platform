import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.profiles import get_profile
from src.route_engine.schema import CircularRouteInput, FallbackReason, RouteOutput
from src.route_engine.scoring.scoring_engine import calculate_custom_score


class CircularLandmarkEngine:
    def __init__(self, inp: CircularRouteInput, G: nx.Graph, landmark_node: int, profile_name: str = "scenic"):
        self._inp           = inp
        self._G             = G.copy()  # 원본 그래프 보호
        self._utils         = PathUtils(self._G)
        self._landmark_node = landmark_node  # 경유 랜드마크 노드
        profile             = get_profile(profile_name)
        self._weights       = profile.weights
        self._blocked_tags  = profile.blocked_tags

    def run(self) -> RouteOutput:
        """
        랜드마크를 경유하는 순환 경로를 생성합니다.
        """
        calculate_custom_score(self._G, {
            "mode": "general",
            "weights": self._weights,
            "blocked_tags": self._blocked_tags,
        })

        start = self._utils.find_nearest_node(self._inp.start_lat, self._inp.start_lon)
        if start is None:
            return RouteOutput(status="FAILED", mode="circular_landmark",
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_NEAREST_START_NODE)

        nodes = self._find_path(start)
        if not nodes:
            return RouteOutput(status="FAILED", mode="circular_landmark",
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_PATH)

        coords  = self._utils.extract_coordinates(nodes)
        total_m = self._calc_distance(nodes)
        return RouteOutput(
            status          = "SUCCESS" if coords else "FAILED",
            mode            = "circular_landmark",
            coordinates     = coords,
            total_km        = round(total_m / 1000, 2),
            fallback_reason = None,
        )

    def _find_path(self, start: int) -> list[int]:
        """
        출발 → 랜드마크 → 출발 경로를 연결합니다.
        """
        try:
            path1       = nx.shortest_path(self._G, start, self._landmark_node, weight="custom_score")
            path1_edges = set(zip(path1[:-1], path1[1:]))

            # _penalize/_restore 대신 callable weight 사용 → 예외 발생 시에도 그래프 오염 없음
            def penalized_weight(u, v, data):
                base = data.get("custom_score", 1.0)
                return base * 100.0 if (u, v) in path1_edges or (v, u) in path1_edges else base

            path2 = nx.shortest_path(self._G, self._landmark_node, start, weight=penalized_weight)
            return path1[:-1] + path2
        except nx.NetworkXNoPath:
            print(f"[landmark/circular] 경로 없음: {start} → {self._landmark_node} → {start}")
            return []
        except Exception as e:
            print(f"[landmark/circular] 오류: {e}")
            return []

    def _penalize(self, path: list[int]) -> dict:
        """
        경로 엣지에 페널티를 적용하고 원본 가중치를 반환합니다.
        """
        saved = {}
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            if self._G.has_edge(u, v):
                saved[(u, v)] = self._G[u][v]["custom_score"]
                self._G[u][v]["custom_score"] *= 100
        return saved

    def _restore(self, saved: dict) -> None:
        """
        페널티 적용 전 가중치를 복원합니다.
        """
        for (u, v), w in saved.items():
            self._G[u][v]["custom_score"] = w

    def _calc_distance(self, nodes: list[int]) -> float:
        """
        노드 목록의 총 이동 거리(미터)를 반환합니다.
        """
        return sum(
            (self._G.get_edge_data(nodes[i], nodes[i + 1]) or {}).get("length", 0)
            for i in range(len(nodes) - 1)
        )


