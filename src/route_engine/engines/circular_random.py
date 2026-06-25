import networkx as nx
import random
from typing import Optional
import logging

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.profiles import ScoringProfile, get_profile, merge_weights
from src.interfaces.schema.walk_schema import (
    WalkMode,
    WalkRouteStatus,
    WalkRouteResponse
)
from src.schema.route_schema import CircularRouteInput, Weights
from src.route_engine.scoring.scoring_engine import calculate_custom_score

logger = logging.getLogger(__name__)

class CircularRandomEngine:
    def __init__(
        self,
        inp: CircularRouteInput,
        G: nx.Graph,
        custom_weights: Optional[Weights] = None,
        profile: Optional[ScoringProfile] = None,
    ):
        self.inp           = inp
        self.G             = G.copy()  # 원본 그래프 보호
        self.utils         = PathUtils(self.G)
        self.mode          = WalkMode.CIRCULAR_RANDOM
        profile_config     = get_profile(profile)
        self.weights       = merge_weights(profile_config.weights, custom_weights)
        self.blocked_tags  = profile_config.blocked_tags
        self.scoring_mode  = profile_config.scoring_mode

    def run(self) -> WalkRouteResponse:
        """
        순환 랜덤 경로를 생성합니다.
        """
        logger.info(f"순환 랜덤 경로 생성 엔진을 시작합니다: target_km={self.inp.target_km}, scoring_mode={self.scoring_mode}, weights={self.weights}")

        # 엣지별 custom_score 기록 (in-place)
        calculate_custom_score(self.G, {
            "mode": self.scoring_mode,
            "weights": self.weights,
            "blocked_tags": self.blocked_tags,
        })

        # 출발 노드 탐색
        start = self.utils.find_nearest_node(self.inp.start_lat, self.inp.start_lon)

        # 출발 노드가 없는 경우
        if start is None:
            logger.warning("출발 노드를 찾지 못했습니다.")
            return WalkRouteResponse(
                status=WalkRouteStatus.NO_NEAREST_START_NODE,
                mode=self.mode,
                coordinates=[],
                total_km=0.0,
            )
        
        # 경로 생성
        nodes = self.find_path(start, self.inp.target_km or 3.0)

        # 경로가 없는 경우
        if not nodes:
            logger.warning("경로가 비어 있습니다.")
            return WalkRouteResponse(
                status=WalkRouteStatus.NO_PATH,
                mode=self.mode,
                coordinates=[],
                total_km=0.0,
            )

        pruned  = self.utils.prune_dead_ends(nodes)       # 왕복 가지 제거
        coords  = self.utils.extract_coordinates(pruned)  # [lat, lon] 좌표 목록
        total_m = self.utils.calc_distance(pruned)        # 총 이동 거리(미터)
        total_km = round(total_m / 1000, 2)

        logger.info(f"total_km: {total_km}")

        return WalkRouteResponse(
            status          = WalkRouteStatus.SUCCESS if coords else WalkRouteStatus.NO_PATH,
            mode            = self.mode,
            coordinates     = coords,
            total_km        = total_km,
        )
    
    def find_path(self, start_node: int, target_km: float = 3.0) -> list[int]:
        """
        custom_score 기반 확률적 랜덤 워크로 순환 경로 노드 목록을 반환합니다.
        """
        target_m   = target_km * 1000  # 목표 거리(미터)
        path_nodes = [start_node]
        total_dist = 0.0
        current    = start_node
        visited: dict = {}             # 엣지별 방문 횟수
        sx = self.G.nodes[start_node].get("lon", 0)  # 출발점 경도
        sy = self.G.nodes[start_node].get("lat", 0)  # 출발점 위도

        while total_dist < target_m * 0.75:  # 목표의 75%까지 탐색
            neighbors = list(self.G.neighbors(current))
            if not neighbors:
                logger.warning("이웃 노드가 없어 탐색을 중단합니다.")
                break

            probs = []
            for n in neighbors:
                ek         = tuple(sorted([current, n]))               # 무방향 엣지 키
                visit_pen  = 1.0 / (1 + visited.get(ek, 0) * 7)        # 재방문 페널티
                degree_pen = 1.0 / (1 + max(0, 3 - self.G.degree(n)))  # 막힌 노드 억제
                score      = (self.G.get_edge_data(current, n) or {}).get("custom_score", 1.0)

                if total_dist / target_m < 0.7:
                    # 전반부: 출발점에서 멀수록 score 작아짐 → 확률 높아짐 (탐색 확장)
                    dx    = self.G.nodes[n].get("lon", 0) - sx
                    dy    = self.G.nodes[n].get("lat", 0) - sy
                    dist  = (dx ** 2 + dy ** 2) ** 0.5
                    score = score / ((dist + 1e-6) ** 2)
                else:
                    # 후반부: 출발점에서 멀수록 score 커짐 → 확률 낮아짐 (귀환 유도)
                    # Dijkstra 복귀 전 워커가 자연스럽게 출발점 방향으로 수렴하도록 함
                    dx    = self.G.nodes[n].get("lon", 0) - sx
                    dy    = self.G.nodes[n].get("lat", 0) - sy
                    dist  = (dx ** 2 + dy ** 2) ** 0.5
                    score = score * (1.0 + dist ** 2 * 1e6)

                probs.append((1.0 / (score + 1e-6)) * visit_pen * degree_pen)

            total_p = sum(probs)
            if total_p == 0:
                logger.warning("선택 확률 합이 0이므로 탐색을 중단합니다.")
                break

            next_node   = random.choices(neighbors, weights=[p / total_p for p in probs], k=1)[0]
            ek          = tuple(sorted([current, next_node]))
            visited[ek] = visited.get(ek, 0) + 1                                          # 방문 횟수 누적
            total_dist += (self.G.get_edge_data(current, next_node) or {}).get("length", 0)
            path_nodes.append(next_node)
            current = next_node

        if path_nodes[-1] != start_node:  # 출발 노드 미복귀 시 최단 경로로 복귀
            try:
                def _return_w(u, v, d):
                    ek = tuple(sorted([u, v]))
                    return d.get("length", 1.0) * (1 + visited.get(ek, 0) * 10)  # 기방문 엣지 패널티

                return_path = nx.shortest_path(self.G, path_nodes[-1], start_node, weight=_return_w)
                path_nodes += return_path[1:]  # 복귀 경로 연결 (중복 노드 제거)
                logger.info("출발점 복귀에 성공했습니다")
            except nx.NetworkXNoPath:
                logger.exception("출발점 복귀에 실패했습니다")

        return path_nodes
