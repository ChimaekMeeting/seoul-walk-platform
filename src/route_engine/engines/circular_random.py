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

# 직선 거리 → 도로망 거리 추정 계수 (서울 도심 블록 구조 기준)
_NETWORK_FACTOR = 1.4


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
        logger.info(
            "순환 랜덤 경로 생성 엔진을 시작합니다: target_km=%s, scoring_mode=%s, weights=%s",
            self.inp.target_km, self.scoring_mode, self.weights,
        )

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

        coords   = self.utils.extract_coordinates(nodes)  # [lat, lon] 좌표 목록
        total_m  = self.utils.calc_distance(nodes)        # 총 이동 거리(미터)
        total_km = round(total_m / 1000, 2)

        logger.info("경로 생성 완료: total_km=%.2f (target=%.2f), 노드=%d개", total_km, self.inp.target_km or 3.0, len(nodes))

        return WalkRouteResponse(
            status          = WalkRouteStatus.SUCCESS if coords else WalkRouteStatus.NO_PATH,
            mode            = self.mode,
            coordinates     = coords,
            total_km        = total_km,
        )

    def find_path(self, start_node: int, target_km: float = 3.0) -> list[int]:
        """
        custom_score 기반 확률적 랜덤 워크로 순환 경로 노드 목록을 반환합니다.

        종료 조건:
            매 스텝마다 현재 위치 → 출발점 직선 거리에 도로망 계수(_NETWORK_FACTOR)를 곱해
            복귀 거리를 추정합니다. (누적 거리 + 추정 복귀 거리) >= target_m * 0.95 이면
            루프를 종료하고 Dijkstra로 복귀합니다.
            이 방식은 고정 비율(0.75)로 멈추는 기존 방식보다 target_km에 훨씬 가깝게 수렴합니다.
        """
        target_m   = target_km * 1000
        path_nodes = [start_node]
        total_dist = 0.0
        current    = start_node
        visited: dict = {}

        s_data = self.G.nodes[start_node]
        sx     = s_data.get("lon", 0)
        sy     = s_data.get("lat", 0)
        s_lat  = s_data.get("lat", 0)
        s_lon  = s_data.get("lon", 0)

        while True:
            # 안전 장치: 목표의 150% 초과 시 강제 중단
            if total_dist > target_m * 1.5:
                logger.warning("목표 거리의 150%% 초과, 강제 중단 (%.0fm)", total_dist)
                break

            # 현재 위치 → 출발점 복귀 거리 추정 (직선 × 도로망 계수)
            c_data   = self.G.nodes[current]
            c_lat    = c_data.get("lat", s_lat)
            c_lon    = c_data.get("lon", s_lon)
            straight = PathUtils._haversine_m(c_lat, c_lon, s_lat, s_lon)
            est_return = straight * _NETWORK_FACTOR

            # 탐색 종료: 누적 + 추정 복귀 >= 목표의 95% (탐색 초반 30% 전에는 체크 안 함)
            if total_dist > target_m * 0.3 and total_dist + est_return >= target_m * 0.95:
                logger.debug(
                    "복귀 시점 도달: 누적=%.0fm, 추정복귀=%.0fm, 합계=%.0fm / 목표=%.0fm",
                    total_dist, est_return, total_dist + est_return, target_m,
                )
                break

            neighbors = list(self.G.neighbors(current))
            if not neighbors:
                logger.warning("이웃 노드가 없어 탐색을 중단합니다.")
                break

            progress = total_dist / target_m
            probs = []

            for n in neighbors:
                ek         = tuple(sorted([current, n]))
                visit_pen  = 1.0 / (1 + visited.get(ek, 0) * 7)
                degree_pen = 1.0 / (1 + max(0, 3 - self.G.degree(n)))
                score      = (self.G.get_edge_data(current, n) or {}).get("custom_score", 1.0)

                dx      = self.G.nodes[n].get("lon", 0) - sx
                dy      = self.G.nodes[n].get("lat", 0) - sy
                dist_sq = dx ** 2 + dy ** 2

                if progress < 0.5:
                    # 전반부: 출발점에서 멀어질수록 확률 높음 (탐색 확장)
                    score = score / (dist_sq + 1e-12)
                elif progress >= 0.7:
                    # 후반부: 출발점에서 가까울수록 확률 높음 (귀환 유도)
                    score = score * (1.0 + dist_sq * 1e6)
                # 중반부 (0.5~0.7): 방향 중립, 점수만으로 선택

                probs.append((1.0 / (score + 1e-6)) * visit_pen * degree_pen)

            total_p = sum(probs)
            if total_p == 0:
                logger.warning("선택 확률 합이 0이므로 탐색을 중단합니다.")
                break

            next_node   = random.choices(neighbors, weights=[p / total_p for p in probs], k=1)[0]
            ek          = tuple(sorted([current, next_node]))
            visited[ek] = visited.get(ek, 0) + 1
            total_dist += (self.G.get_edge_data(current, next_node) or {}).get("length", 0)
            path_nodes.append(next_node)
            current = next_node

        # 출발점 미복귀 시 최단 경로로 복귀 (기방문 엣지에 페널티)
        if path_nodes[-1] != start_node:
            try:
                def _return_w(u, v, d):
                    ek = tuple(sorted([u, v]))
                    return d.get("length", 1.0) * (1 + visited.get(ek, 0) * 10)

                return_path = nx.shortest_path(self.G, path_nodes[-1], start_node, weight=_return_w)
                path_nodes += return_path[1:]
                logger.info("출발점 복귀 성공: 복귀 경로 %d 노드", len(return_path) - 1)
            except nx.NetworkXNoPath:
                logger.exception("출발점 복귀에 실패했습니다")

        return path_nodes
