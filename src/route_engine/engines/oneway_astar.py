import networkx as nx
from typing import Optional, List
import logging

from src.route_engine.engines.path_utils import PathUtils, _RETURN_REVISIT_PENALTY
from src.route_engine.profiles import ScoringProfile, get_profile, merge_weights
from src.interfaces.schema.walk_schema import (
    WalkMode,
    WalkRouteStatus,
    WalkRouteResponse
)
from src.schema.route_schema import OnewayRouteInput, Weights
from src.route_engine.scoring.scoring_engine import compute_custom_score_lookup

logger = logging.getLogger(__name__)

class OnewayAstarEngine:
    def __init__(
        self,
        inp: OnewayRouteInput,
        G: nx.Graph,
        custom_weights: Optional[Weights] = None,
        profile: Optional[ScoringProfile] = None,
        visited_nodes: Optional[set] = None,
    ):
        self.inp           = inp
        self.G             = G  # custom_score를 그래프에 쓰지 않으므로 copy() 불필요
        self.utils         = PathUtils(self.G)
        self.mode          = WalkMode.ONEWAY_SHORTEST
        profile_config     = get_profile(profile)
        self.weights       = merge_weights(profile_config.weights, custom_weights)
        self.blocked_tags  = profile_config.blocked_tags
        self.scoring_mode  = profile_config.scoring_mode
        self._weight_fn    = None
        self._score_lookup: dict = {}
        self._min_ratio    = 1.0
        # WaypointComposerEngine이 leg 간 경로 겹침을 페널티로 방지할 때 채워줌. 기본(빈 set)이면 기존 동작과 동일.
        self.visited_nodes = visited_nodes or set()
        self.last_path_nodes: list[int] = []  # 가장 최근 run()이 실제로 사용한 노드열(WaypointComposerEngine이 다음 leg의 visited_nodes 누적에 사용)
        # OnewayBeamEngine과 인터페이스를 맞추기 위한 필드. A*는 항상 후보가 1개뿐이라
        # 실질적으로 [last_path_nodes]와 같지만, WaypointComposerEngine이 leg 엔진 종류와
        # 무관하게 같은 방식으로 후보별 노드열을 조회할 수 있게 해준다.
        self.last_path_nodes_by_candidate: list[list[int]] = []

    def run(self) -> List[WalkRouteResponse]:
        """
        A* 최단 경로를 생성합니다.
        """
        logger.info(f"최단 경로 생성 엔진(A*)을 시작합니다: scoring_mode={self.scoring_mode}, weights={self.weights}")

        scored = compute_custom_score_lookup(self.G, {
            "mode": self.scoring_mode,
            "weights": self.weights,
            "blocked_tags": self.blocked_tags,
        })
        self._weight_fn    = scored["weight"]
        self._score_lookup = scored["lookup"]
        self._min_ratio    = scored["min_ratio"]

        # 출발 노드와 도착 노드 탐색
        start = self.utils.find_nearest_node(self.inp.start_lat, self.inp.start_lon)
        end   = self.utils.find_nearest_node(self.inp.end_lat,   self.inp.end_lon)

        if start is None:
            logger.warning("출발 노드를 찾지 못했습니다.")
            return [WalkRouteResponse(
                status=WalkRouteStatus.NO_NEAREST_START_NODE,
                mode=self.mode, coordinates=[], total_km=0.0,
            )]

        if end is None:
            logger.warning("도착 노드를 찾지 못했습니다.")
            return [WalkRouteResponse(
                status=WalkRouteStatus.NO_NEAREST_END_NODE,
                mode=self.mode, coordinates=[], total_km=0.0,
            )]

        # 경로 생성 (경로 후보가 리스트에 감싸져서 반환됨)
        candidates = self.find_path(start, end)

        if not candidates:
            logger.warning("경로가 비어 있습니다.")
            return [WalkRouteResponse(
                status=WalkRouteStatus.NO_PATH,
                mode=self.mode, coordinates=[], total_km=0.0,
            )]

        nodes     = candidates[0]                          # 경로 1개만 사용
        self.last_path_nodes = nodes
        self.last_path_nodes_by_candidate = [nodes]
        coords    = self.utils.extract_coordinates(nodes)
        total_m   = self.utils.calc_distance(nodes)
        total_km = round(total_m / 1000, 2)

        logger.info(f"total_km: {total_km}")

        return [WalkRouteResponse(
            status          = WalkRouteStatus.SUCCESS if coords else WalkRouteStatus.NO_PATH,
            mode            = self.mode,
            coordinates     = coords,
            total_km        = total_km,
        )]

    def find_path(self, start: int, end: int) -> list[list[int]]:
        """
        A* 알고리즘으로 최단 경로 노드 목록을 반환합니다.
        """
        def _weight(u, v, d):
            # PathUtils.connect_to와 동일한 패턴: 도착지 자신은 페널티 대상에서 제외한다.
            base = self._weight_fn(u, v, d)
            if v in self.visited_nodes and v != end:
                return base * _RETURN_REVISIT_PENALTY
            return base

        try:
            return [nx.astar_path(
                self.G, start, end,
                heuristic=self._heuristic,
                weight=_weight,
            )]
        except nx.NetworkXNoPath:
            logger.warning("출발-도착 노드 사이에 연결된 경로가 없습니다")
            return []
        except Exception:
            logger.exception("최단 경로 생성에 실패했습니다")
            return []

    def path_cost(self, path: list[int]) -> float:
        """경로(노드 리스트)의 누적 custom_score. 벤치마크 solver의 cost 계산용."""
        return sum(
            self._score_lookup.get((path[i], path[i + 1]), 1.0)
            for i in range(len(path) - 1)
        )

    def _heuristic(self, node: int, target: int) -> float:
        """
        A* 휴리스틱: 랜드마크 삼각부등식 기반 도로망거리 추정 × 최소 비용/거리 비율.
        """
        d_node   = self.G.nodes[node]["landmark_dist"]
        d_target = self.G.nodes[target]["landmark_dist"]
        network_est = max(abs(a - b) for a, b in zip(d_node, d_target))
        return network_est * self._min_ratio


def precompute_landmarks(G: nx.Graph) -> None:
    """
    그래프 경계 근처 8개 노드를 랜드마크로 선정하고, 각 랜드마크에서 전체 노드까지의
    실제 도로망 거리(m, length 기준 — 프로필 무관)를 미리 계산해 노드 속성에 저장합니다.
    그래프 로드 시 한 번만 호출하면 되고, 프로필이 달라져도 재계산할 필요 없습니다.
    """
    landmarks = _select_landmarks(G)
    for lm in landmarks:
        dist = nx.single_source_dijkstra_path_length(G, lm, weight="length")
        for node in G.nodes:
            G.nodes[node].setdefault("landmark_dist", []).append(dist.get(node, float("inf")))
    G.graph["landmark_nodes"] = landmarks


def _select_landmarks(G: nx.Graph) -> list[int]:
    """
    위도/경도 극값(동서남북 + 대각선 4방향) 근처 노드를 랜드마크로 선정합니다.
    """
    nodes = list(G.nodes(data=True))
    by_lat = sorted(nodes, key=lambda nd: nd[1].get("lat", 0))
    by_lon = sorted(nodes, key=lambda nd: nd[1].get("lon", 0))
    candidates = {by_lat[0][0], by_lat[-1][0], by_lon[0][0], by_lon[-1][0]}
    candidates.add(min(nodes, key=lambda nd: nd[1].get("lat", 0) + nd[1].get("lon", 0))[0])
    candidates.add(max(nodes, key=lambda nd: nd[1].get("lat", 0) + nd[1].get("lon", 0))[0])
    candidates.add(max(nodes, key=lambda nd: nd[1].get("lat", 0) - nd[1].get("lon", 0))[0])
    candidates.add(min(nodes, key=lambda nd: nd[1].get("lat", 0) - nd[1].get("lon", 0))[0])
    return list(candidates)
