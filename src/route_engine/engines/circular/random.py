import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.profiles import get_profile
from src.route_engine.schema import CircularRouteInput, FallbackReason, RouteOutput
from src.route_engine.scoring.scoring_engine import calculate_custom_score


class CircularRandomEngine:
    def __init__(self, inp: CircularRouteInput, G: nx.Graph, profile_name: str = "default"):
        self._inp          = inp
        self._G            = G.copy()  # 원본 그래프 보호
        self._utils        = PathUtils(self._G)
        profile            = get_profile(profile_name)
        self._weights      = profile.weights
        self._blocked_tags = profile.blocked_tags

    def run(self) -> RouteOutput:
        """
        순환 랜덤 경로를 생성합니다.
        """
        calculate_custom_score(self._G, {
            "mode": "general",
            "weights": self._weights,
            "blocked_tags": self._blocked_tags,
        })

        start = self._utils.find_nearest_node(self._inp.start_lat, self._inp.start_lon)
        if start is None:
            return RouteOutput(status="FAILED", mode="circular_random",
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_NEAREST_START_NODE)

        nodes = self._utils.circular_random_walk(start, self._inp.target_km or 3.0)
        if not nodes:
            return RouteOutput(status="FAILED", mode="circular_random",
                               coordinates=[], total_km=0.0,
                               fallback_reason=FallbackReason.NO_PATH)

        pruned  = self._utils.prune_dead_ends(nodes)
        coords  = self._utils.extract_coordinates(pruned)
        total_m = self._calc_distance(pruned)
        return RouteOutput(
            status          = "SUCCESS" if coords else "FAILED",
            mode            = "circular_random",
            coordinates     = coords,
            total_km        = round(total_m / 1000, 2),
            fallback_reason = None,
        )

    def _calc_distance(self, nodes: list[int]) -> float:
        """
        노드 목록의 총 이동 거리(미터)를 반환합니다.
        """
        return sum(
            (self._G.get_edge_data(nodes[i], nodes[i + 1]) or {}).get("length", 0)
            for i in range(len(nodes) - 1)
        )

