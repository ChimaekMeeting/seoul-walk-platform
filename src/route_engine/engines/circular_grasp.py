import random
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

_GRASP_ITERS = 24  # GRASP 반복 횟수(= 서로 다른 초기 해를 만드는 횟수)
_RCL_SIZE = 8      # RCL 크기: 랜덤 선택 전 상위 몇 개로 좁힐지 (beam 폭과 무관한 튜닝값)
_MAX_STEPS = 400   # 구성 단계 최대 확장 횟수 (무한 루프 방지용 상한)
_SEED = 42         # 난수 시드 고정 → 동일 입력이면 100% 동일 경로(재현성)


class CircularGraspEngine:
    def __init__(
        self,
        inp: CircularRouteInput,
        G: nx.Graph,
        custom_weights: Optional[Weights] = None,
        profile: Optional[ScoringProfile] = None,
        seed: int = _SEED,
    ):
        self.inp           = inp
        self.G             = G.copy()  # 원본 그래프 보호
        self.utils         = PathUtils(self.G)
        self.mode          = WalkMode.CIRCULAR_RANDOM
        self.seed          = seed      # 재현성 보장을 위한 시드
        profile_config     = get_profile(profile)
        self.weights       = merge_weights(profile_config.weights, custom_weights)
        self.blocked_tags  = profile_config.blocked_tags
        self.scoring_mode  = profile_config.scoring_mode

    def run(self) -> WalkRouteResponse:
        """
        순환 경로를 생성합니다.
        """
        logger.info(
            "순환 GRASP 경로 생성 엔진을 시작합니다: target_km=%s, scoring_mode=%s, weights=%s",
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

        logger.info("경로 생성 완료: total_km=%.2f (target=%.2f), 노드=%d개",
                    total_km, self.inp.target_km or 3.0, len(nodes))

        return WalkRouteResponse(
            status          = WalkRouteStatus.SUCCESS if coords else WalkRouteStatus.NO_PATH,
            mode            = self.mode,
            coordinates     = coords,
            total_km        = total_km,
        )

    def find_path(self, start_node: int, target_km: float = 3.0) -> list[int]:
        """
        GRASP + VNS 기반 순환 경로를 생성합니다.
        """
        target_m = target_km * 1000  # 목표 거리를 미터 단위로 환산함
        rng = random.Random(self.seed)  # 엔진 전용 난수 인스턴스 → 재현성 보장

        # 1단계 + 1.5단계: 출발지 -> 반환점 경로 생성 + 후보(pool) 구성
        pool = self._build_pool(start_node, target_m, rng)

        # 2·3단계: 반환점 -> 출발지 경로 이어 생성 + 가장 좋은 완성 경로 1개 채택
        best_path, best_key = None, None
        for cost, nodes, dist, visited in pool:
            closed = self._find_waypoint_to_start(nodes, visited, start_node)  # 2단계: 반환점 -> 출발지
            if closed is None:
                continue  # 복귀 불가한 해는 폐기
            improved = self._improve(closed, target_m)  # 3단계: VND 개선
            key = self.utils.route_key(improved, target_m)
            if best_key is None or key < best_key:
                best_key, best_path = key, improved

        # 모든 후보가 복귀에 실패한 경우의 방어 코드
        if best_path is None:
            logger.warning("GRASP 후보가 비어 출발 노드만 반환합니다.")
            return [start_node]

        logger.info("GRASP 순환 경로 선택: 노드=%d개, 거리초과=%.0fm, 품질밀도=%.3f",
                    len(best_path), best_key[0], best_key[1])
        return best_path

    def _find_start_to_waypoint(self, start_node: int, target_m: float, rng: random.Random) -> tuple:
        """
        1단계: 출발지 → 반환지 경로를 1개 생성합니다.
        """
        nodes   = [start_node]
        visited = {start_node}
        dist    = 0.0
        cost    = 0.0
        for _ in range(_MAX_STEPS):
            current    = nodes[-1]
            est_return = self.utils.est_network_dist(current, start_node)

            # 종료 판정: 누적거리 + 예상 복귀거리 ≥ 목표의 95% → 반환 시점으로 간주
            # 누적 거리가 목표의 30%를 넘긴 뒤부터만 검사 → 너무 이른 종료 방지
            if dist > target_m * 0.3 and dist + est_return >= target_m * 0.95:
                break

            # 미방문 이웃을 한 걸음 확장한 후보로 평가 — beam과 동일한 objective 사용
            #   objective(누적거리 + 예상 복귀거리,  누적거리,  누적비용)
            #   = (|실제 오차| - 허용 오차,  품질밀도)
            candidates = []
            for n in sorted(self.G.neighbors(current)):
                if n in visited:
                    continue  # 이미 방문한 노드 제외

                edge      = self.G.get_edge_data(current, n) or {}
                step_cost = edge.get("custom_score", 1.0)
                step_len  = edge.get("length", 0)
                new_dist  = dist + step_len
                new_cost  = cost + step_cost
                score     = self.utils.objective(
                    new_dist + self.utils.est_network_dist(n, start_node),
                    new_dist, new_cost, target_m
                )
                candidates.append((score, n, step_len, step_cost))

            if not candidates:
                break  # 모든 길이 막힌 경우 종료

            # RCL: 평가값 상위 k개로 좁힌 뒤(결정론) 그중 무작위 1개 선택
            candidates.sort(key=lambda c: (c[0], c[1]))  # (평가값, node_id) → 결정론적 순서
            rcl = candidates[:_RCL_SIZE]

            _, n_sel, len_sel, cost_sel = rng.choice(rcl)  # 고정 시드 rng → 재현 보장
            nodes.append(n_sel)
            visited.add(n_sel)
            dist += len_sel
            cost += cost_sel
        return cost, nodes, dist, visited

    def _build_pool(self, start_node: int, target_m: float, rng: random.Random) -> list:
        """
        1.5단계: 1단계 구성을 _GRASP_ITERS번 반복해 서로 다른 경로 후보(pool)를 구성합니다.
        """
        pool = []
        for _ in range(_GRASP_ITERS):
            pool.append(self._find_start_to_waypoint(start_node, target_m, rng))
        return pool

    def _find_waypoint_to_start(self, nodes: list[int], visited: set, start_node: int):
        """
        2단계: 반환지 → 출발지 경로를 생성합니다.
        """
        return self.utils.connect_to(nodes, visited, start_node)
    
    def _improve(self, path: list[int], target_m: float) -> list[int]:
        """
        3단계: 노드 제거 + 추가를 통해 경로를 개선합니다.
        """
        neighborhoods = [self._neighbor_remove, self._neighbor_insert]
        l = 0
        while l < len(neighborhoods):
            improved = neighborhoods[l](path, target_m)
            if improved is not None:
                path = improved
                l = 0        # 개선 시 첫 이웃으로 복귀(VNS 핵심)
            else:
                l += 1        # 개선 없으면 다음 이웃으로 전환
        return path

    def _neighbor_remove(self, path: list[int], target_m: float):
        """
        노드를 제거합니다.
        """
        best_path, best_key = None, self.utils.route_key(path, target_m)
        for i in range(1, len(path) - 1):
            a, m, b = path[i - 1], path[i], path[i + 1]
            if a == b or not self.G.has_edge(a, b):
                continue
            candidate = path[:i] + path[i + 1:]
            key = self.utils.route_key(candidate, target_m)
            if key < best_key:
                best_key, best_path = key, candidate
        return best_path  # 개선되지 않았으면 None 반환

    def _neighbor_insert(self, path: list[int], target_m: float):
        """
        노드를 추가합니다.
        """
        in_path = set(path)
        best_path, best_key = None, self.utils.route_key(path, target_m)
        for i in range(len(path) - 1):
            a, b = path[i], path[i + 1]
            for x in sorted(set(self.G.neighbors(a)) & set(self.G.neighbors(b))):
                if x in in_path:
                    continue
                candidate = path[:i + 1] + [x] + path[i + 1:]
                key = self.utils.route_key(candidate, target_m)
                if key < best_key:
                    best_key, best_path = key, candidate
        return best_path  # 개선되지 않았으면 None 반환