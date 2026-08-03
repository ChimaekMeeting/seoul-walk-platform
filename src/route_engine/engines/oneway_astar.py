import networkx as nx
from typing import Optional
import logging

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.profiles import ScoringProfile, get_profile, merge_weights
from src.interfaces.schema.walk_schema import (
    WalkMode,
    WalkRouteStatus,
    WalkRouteResponse
)
from src.schema.route_schema import OnewayRouteInput, Weights
from src.route_engine.scoring.scoring_engine import calculate_custom_score

logger = logging.getLogger(__name__)
_NUM_LANDMARKS = 8  # 그래프 경계 8방향(동서남북+대각선) 기준

class OnewayAstarEngine:
    def __init__(
        self,
        inp: OnewayRouteInput,
        G: nx.Graph,
        custom_weights: Optional[Weights] = None,
        profile: Optional[ScoringProfile] = None,
    ):
        self.inp           = inp
        self.G             = G.copy()  # 원본 그래프 보호
        self.utils         = PathUtils(self.G)
        self.mode          = WalkMode.ONEWAY_SHORTEST
        profile_config     = get_profile(profile)
        self.weights       = merge_weights(profile_config.weights, custom_weights)
        self.blocked_tags  = profile_config.blocked_tags
        self.scoring_mode  = profile_config.scoring_mode

    def run(self) -> WalkRouteResponse:
        """
        A* 최단 경로를 생성합니다.
        """
        logger.info(f"최단 경로 생성 엔진(A*)을 시작합니다: scoring_mode={self.scoring_mode}, weights={self.weights}")

        # 엣지별 custom_score 기록 (in-place)
        calculate_custom_score(self.G, {
            "mode": self.scoring_mode,
            "weights": self.weights,
            "blocked_tags": self.blocked_tags,
        })
        self._min_ratio = self._min_cost_per_m()  # A* admissibility용 최소 비용/거리 비율


        # 출발 노드와 도착 노드 탐색
        start = self.utils.find_nearest_node(self.inp.start_lat, self.inp.start_lon)
        end   = self.utils.find_nearest_node(self.inp.end_lat,   self.inp.end_lon)

        # 출발 노드가 없는 경우
        if start is None:
            logger.warning("출발 노드를 찾지 못했습니다.")
            return WalkRouteResponse(
                status=WalkRouteStatus.NO_NEAREST_START_NODE,
                mode=self.mode,
                coordinates=[],
                total_km=0.0,
            )

        # 도착 노드가 없는 경우
        if end is None:
            logger.warning("도착 노드를 찾지 못했습니다.")
            return WalkRouteResponse(
                status=WalkRouteStatus.NO_NEAREST_END_NODE,
                mode=self.mode,
                coordinates=[],
                total_km=0.0,
            )

        # 경로 생성
        nodes = self.find_path(start, end)

        # 경로가 없는 경우
        if not nodes:
            logger.warning("경로가 비어 있습니다.")
            return WalkRouteResponse(
                status=WalkRouteStatus.NO_PATH,
                mode=self.mode,
                coordinates=[],
                total_km=0.0,
            )

        coords    = self.utils.extract_coordinates(nodes)  # [lat, lon] 좌표 목록
        total_m   = self.utils.calc_distance(nodes)        # 총 이동 거리(m)
        total_km = round(total_m / 1000, 2)

        logger.info(f"total_km: {total_km}")

        return WalkRouteResponse(
            status          = WalkRouteStatus.SUCCESS if coords else WalkRouteStatus.NO_PATH,
            mode            = self.mode,
            coordinates     = coords,
            total_km        = total_km,
        )

    def find_path(self, start: int, end: int) -> list[int]:
        """
        A* 알고리즘으로 최단 경로 노드 목록을 반환합니다.
        """
        try:
            path = nx.astar_path(
                self.G, start, end,
                heuristic=self._heuristic,
                weight="custom_score",
            )
            return path
        except nx.NetworkXNoPath:
            logger.warning("출발-도착 노드 사이에 연결된 경로가 없습니다")
            return []
        except Exception:
            logger.exception("최단 경로 생성에 실패했습니다")
            return []

    def _min_cost_per_m(self) -> float:
        """
        그래프 전체에서 (custom_score / length)의 최솟값.
        직선거리(m) × 이 값은 항상 실제 비용의 하한 — A* admissibility 보장용.
        """
        return min(
            (data.get("custom_score", 1.0) / max(data.get("length", 1.0) or 1.0, 1e-6))
            for _, _, data in self.G.edges(data=True)
        )

    def _heuristic(self, node: int, target: int) -> float:
        """
        A* 휴리스틱: 랜드마크 삼각부등식 기반 도로망거리 추정 × 최소 비용/거리 비율.
        """
        self._heuristic_calls = getattr(self, "_heuristic_calls", 0) + 1
        d_node   = self.G.nodes[node]["landmark_dist"]
        d_target = self.G.nodes[target]["landmark_dist"]
        network_est = max(abs(a - b) for a, b in zip(d_node, d_target))
        return network_est * self._min_ratio
    
def precompute_landmarks(G: nx.Graph) -> None:
    """
    그래프 경계 근처 8개 노드를 랜드마크로 선정하고, 각 랜드마크에서 전체 노드까지의
    실제 도로망 거리(m, length 기준 — 프로필 무관)를 미리 계산해 노드 속성에 저장합니다.
    A* 휴리스틱에서 삼각부등식 기반 하한(ALT)으로 사용합니다.
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