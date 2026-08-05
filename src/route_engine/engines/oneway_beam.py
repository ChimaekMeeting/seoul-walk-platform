import networkx as nx
from typing import Optional, List
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

_BEAM_WIDTH = 8   # 동시에 유지할 후보 경로 개수
_MAX_STEPS = 400  # 빔 확장 최대 반복 횟수

class OnewayBeamEngine:
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
        self.mode          = WalkMode.ONEWAY_RANDOM
        profile_config     = get_profile(profile)
        self.weights       = merge_weights(profile_config.weights, custom_weights)
        self.blocked_tags  = profile_config.blocked_tags
        self.scoring_mode  = profile_config.scoring_mode

    def run(self) -> List[WalkRouteResponse]:
        """
        우회 편도 경로를 생성합니다.
        """
        logger.info(f"랜덤 편도 경로 생성 엔진을 시작합니다: target_km={self.inp.target_km}, scoring_mode={self.scoring_mode}, weights={self.weights}")

        # 엣지별 custom_score 기록 (in-place)
        calculate_custom_score(self.G, {
            "mode": self.scoring_mode,
            "weights": self.weights,
            "blocked_tags": self.blocked_tags,
        })

        # 출발 노드와 도착 노드 탐색
        start = self.utils.find_nearest_node(self.inp.start_lat, self.inp.start_lon)  # 출발 노드
        end   = self.utils.find_nearest_node(self.inp.end_lat,   self.inp.end_lon)    # 도착 노드

        # 출발 노드가 없는 경우
        if start is None:
            logger.warning("출발 노드를 찾지 못했습니다.")
            return [WalkRouteResponse(
                status=WalkRouteStatus.NO_NEAREST_START_NODE,
                mode=self.mode,
                coordinates=[],
                total_km=0.0,
            )]

        # 도착 노드가 없는 경우
        if end is None:
            logger.warning("도착 노드를 찾지 못했습니다.")
            return [WalkRouteResponse(
                status=WalkRouteStatus.NO_NEAREST_END_NODE,
                mode=self.mode,
                coordinates=[],
                total_km=0.0,
            )]

        # 경로 생성 (경로 후보가 리스트에 감싸져서 반환됨)
        candidates = self.find_path(start, end, self.inp.target_km or 3.0)

        # 경로가 없는 경우
        if not candidates:
            logger.warning("경로가 비어 있습니다.")
            return [WalkRouteResponse(
                status=WalkRouteStatus.NO_PATH,
                mode=self.mode,
                coordinates=[],
                total_km=0.0,
            )]

        nodes    = candidates[0]                            # 경로 1개만 사용
        pruned   = self.utils.prune_dead_ends(nodes)       # 왕복 가지 제거
        coords   = self.utils.extract_coordinates(pruned)  # [lat, lon] 좌표 목록
        total_m  = self.utils.calc_distance(pruned)        # 총 이동 거리(m)
        total_km = round(total_m / 1000, 2)

        logger.info(f"total_km: {total_km}")

        return [WalkRouteResponse(
            status          = WalkRouteStatus.SUCCESS if coords else WalkRouteStatus.NO_PATH,
            mode            = self.mode,
            coordinates     = coords,
            total_km        = total_km,
        )]

    def find_path(self, start: int, end: int, target_km: float = 3.0) -> list[list[int]]:
        """
        beam search 기반 우회 편도 경로를 생성합니다.
        """
        target_m = target_km * 1000  # 목표 거리를 미터로 환산함

        # custom_score 기준 최단경로 — 우회 실패/불가 시의 최종 대체 경로로도 사용함
        try:
            base_shortest = nx.shortest_path(self.G, start, end, weight="custom_score")
        except nx.NetworkXNoPath:
            logger.warning("출발-도착 간 경로가 존재하지 않습니다.")
            return []

        base_edges = {
            frozenset((base_shortest[i], base_shortest[i + 1]))
            for i in range(len(base_shortest) - 1)
        }  # 우회도 계산 기준 — 베이스 최단경로와 겹치는 구간 판별용

        # 1단계: 출발지 → 중간지점
        finished, beams = self._find_start_to_waypoint(start, end, target_m, base_edges)

        # 1.5단계: 후보 풀 구성
        pool = self._build_pool(finished, beams)
        if not pool:
            logger.warning("beam search 후보가 비어 최단 경로로 대체합니다.")
            return [base_shortest]

        # 2단계: 중간지점 → 도착지 + 가장 좋은 완성 경로 1개 채택
        best_path, best_key = None, None
        for cost, nodes, dist, visited in pool:
            closed = self._find_waypoint_to_end(nodes, visited, end)
            if closed is None:
                continue  # 도착 연결 불가 후보는 제외함
            over, density, path_tuple = self.utils.route_key(closed, target_m)
            overlap = self._overlap_ratio(closed, base_edges)
            key = (over, overlap, density, path_tuple)  # 거리 합격 → 우회도 → 품질밀도 순으로 비교
            if best_key is None or key < best_key:
                best_key, best_path = key, closed

        # 모든 후보가 도착 연결에 실패한 경우의 방어 코드
        if best_path is None:
            logger.warning("도착 연결 가능한 후보가 없어 최단 경로로 대체합니다.")
            return [base_shortest]

        logger.info("beam search 편도 경로 선택: 노드=%d개, 거리초과=%.0fm, 우회도=%.3f, 품질밀도=%.3f",
                    len(best_path), best_key[0], best_key[1], best_key[2])
        return [best_path]


    def _overlap_ratio(self, path: list[int], base_edges: set) -> float:
        """
        path가 base_edges(베이스 최단경로 구간)와 겹치는 거리 비율을 반환합니다.
        낮을수록 베이스 경로와 다른 길로 우회했다는 뜻입니다.
        """
        total_m = sum(
            (self.G.get_edge_data(path[i], path[i + 1]) or {}).get("length", 0)
            for i in range(len(path) - 1)
        )
        if total_m <= 0:
            return 0.0
        overlap_m = sum(
            (self.G.get_edge_data(path[i], path[i + 1]) or {}).get("length", 0)
            for i in range(len(path) - 1)
            if frozenset((path[i], path[i + 1])) in base_edges
        )
        return round(overlap_m / total_m, 4)


    def _find_start_to_waypoint(self, start: int, end: int, target_m: float, base_edges: set) -> tuple:
        """
        1단계: 출발지 → 중간지점 경로를 생성합니다.
        """
        def _rank_key(b):
            # 거리 합격(over) → 우회도(overlap) → 품질(density) 순으로 비교
            over, density = self.utils.objective(
                b[2] + self.utils.est_network_dist(b[1][-1], end), b[2], b[0], target_m)
            overlap = self._overlap_ratio(b[1], base_edges)
            return (over, overlap, density, b[1])

        beams = [(0.0, [start], 0.0, {start})]
        finished: list = []  # 도착에 닿았거나 연결 시점에 도달한 빔을 모으는 목록

        for _ in range(_MAX_STEPS):
            if not beams:
                break

            candidates: list = []  # 이번 스텝의 모든 확장 후보를 담는 목록
            for cost, nodes, dist, visited in beams:
                current = nodes[-1]

                # 도착 노드에 이미 닿았으면 완성 경로 → 후보로 보관함
                if current == end:
                    finished.append((cost, nodes, dist, visited))
                    continue

                est_to_end = self.utils.est_network_dist(current, end)

                # 종료 판정: 누적거리 + 도착점까지의 예상 거리 ≥ 목표의 95% → 도착점으로 나아갈 시점
                # 누적 거리가 목표의 30%를 넘긴 뒤부터만 검사 → 너무 이른 종료 방지
                if dist > target_m * 0.3 and dist + est_to_end >= target_m * 0.95:
                    finished.append((cost, nodes, dist, visited))
                    continue

                # 이웃을 node_id 오름차순으로 순회함 → 순서 고정(결정론의 핵심)
                for n in sorted(self.G.neighbors(current)):
                    if n in visited:
                        continue  # 노드 재방문 금지 → 단순 경로 → 왕복 가지 차단

                    edge = self.G.get_edge_data(current, n) or {}
                    candidates.append((
                        cost + edge.get("custom_score", 1.0),  # 누적 비용 갱신
                        nodes + [n],                           # 노드열 갱신
                        dist + edge.get("length", 0),          # 누적 거리 갱신
                        visited | {n},                         # 방문 집합 갱신
                    ))

            if not candidates:
                break

            candidates.sort(key=_rank_key)
            beams = candidates[:_BEAM_WIDTH]

        return finished, beams


    def _build_pool(self, finished: list, beams: list) -> list:
        """
        1.5단계: 후보 풀을 구성합니다.
        """
        return finished if finished else beams

    def _find_waypoint_to_end(self, nodes: list[int], visited: set, end: int):
        """
        2단계: 한 후보의 중간지점 → 도착지 경로를 생성합니다.
        """
        return self.utils.connect_to(nodes, visited, end)