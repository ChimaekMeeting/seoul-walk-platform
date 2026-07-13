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
from src.schema.route_schema import CircularRouteInput, Weights
from src.route_engine.scoring.scoring_engine import calculate_custom_score

logger = logging.getLogger(__name__)

_BEAM_WIDTH = 8   # 동시에 유지할 후보 경로 개수
_MAX_STEPS = 400  # 빔 확장 최대 반복 횟수

class CircularBeamEngine:
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
        순환 경로를 생성합니다.
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

        pruned   = self.utils.prune_dead_ends(nodes)       # 왕복 가지 제거
        coords   = self.utils.extract_coordinates(pruned)  # [lat, lon] 좌표 목록
        total_m  = self.utils.calc_distance(pruned)        # 총 이동 거리(미터)
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
        beam search 기반 순환 경로를 생성합니다.
        """
        target_m = target_km * 1000  # 목표 거리를 미터 단위로 환산함

        # 1단계: 출발지 → 반환점
        finished, beams = self._find_start_to_waypoint(start_node, target_m)

        # 1.5단계: 반환 후보 풀 구성
        pool = self._build_pool(finished, beams)
        if not pool:
            logger.warning("beam search 후보가 비어 출발 노드만 반환합니다.")
            return [start_node]

        # 2단계: 반환점 → 출발지 + 가장 좋은 완성 경로 1개 채택
        best_path, best_key = None, None
        for cost, nodes, dist, visited in pool:
            closed = self._find_waypoint_to_start(nodes, visited, start_node)
            if closed is None:
                continue  # 출발점으로 복귀 불가한 후보는 제외
            key = self.utils.route_key(closed, target_m)  # (|실제 오차| - 허용 오차, 누적 비용 / 거리, 노드열)
            if best_key is None or key < best_key:
                best_key, best_path = key, closed

        # 모든 후보가 복귀에 실패한 경우의 방어 코드
        if best_path is None:
            logger.warning("복귀 가능한 후보가 없어 첫 후보의 바깥 경로를 반환합니다.")
            return pool[0][1]

        logger.info("beam search 경로 선택: 노드=%d개, 거리초과=%.0fm, 품질밀도=%.3f",
                    len(best_path), best_key[0], best_key[1])
        return best_path

    def _find_start_to_waypoint(self, start_node: int, target_m: float) -> tuple:
        """
        1단계: 출발지 → 반환점 경로를 생성합니다.
        """
        beams = [(0.0, [start_node], 0.0, {start_node})]
        finished: list = []  # 복귀 시점에 도달한 빔들을 모으는 목록

        for _ in range(_MAX_STEPS):
            if not beams:
                break

            candidates: list = []  # 이번 스텝에서 생성된 모든 확장 후보를 담는 목록

            for cost, nodes, dist, visited in beams:
                current    = nodes[-1]  # 해당 빔의 현재(마지막) 노드
                est_return = self.utils.est_network_dist(current, start_node)

                # 종료 판정: 누적거리 + 예상 복귀거리 ≥ 목표의 95% → 복귀 시점으로 간주
                # 누적 거리가 목표의 30%를 넘긴 뒤부터만 검사 → 너무 이른 종료 방지
                if dist > target_m * 0.3 and dist + est_return >= target_m * 0.95:
                    finished.append((cost, nodes, dist, visited))
                    continue  # 이 빔은 확장 중단하고 복귀 후보로 보관

                # 이웃을 node_id 오름차순으로 순회 → 결정론적 탐색 보장
                for n in sorted(self.G.neighbors(current)):
                    if n in visited:
                        continue  # 이미 방문한 노드 제외

                    edge = self.G.get_edge_data(current, n) or {}
                    candidates.append((
                        cost + edge.get("custom_score", 1.0),  # 누적 비용 갱신
                        nodes + [n],                           # 노드열 갱신
                        dist + edge.get("length", 0),          # 누적 거리 갱신
                        visited | {n},                         # 방문 집합 갱신
                    ))

            if not candidates:
                break  # 모든 길이 막힌 경우 종료

            # 결정론적 상위 k 선별
            # b = (누적 비용, 노드열, 누적 거리, 방문 집합)
            # objective(누적거리 + 예상 복귀거리, 누적거리, 누적비용) → (|실제 오차| - 허용 오차, 누적 비용 / 거리)
            candidates.sort(key=lambda b: self.utils.objective(
                b[2] + self.utils.est_network_dist(b[1][-1], start_node),
                b[2], b[0], target_m) + (b[1],)
            )
            beams = candidates[:_BEAM_WIDTH]  # 상위 k개만 남김

        return finished, beams

    def _build_pool(self, finished: list, beams: list) -> list:
        """
        1.5단계: 반환 후보 풀을 구성합니다.
        """
        return finished if finished else beams

    def _find_waypoint_to_start(self, nodes: list[int], visited: set, start_node: int):
        """
        2단계: 반환점 → 출발지까지의 경로를 이어서 생성합니다.
        """
        return self.utils.connect_to(nodes, visited, start_node)
