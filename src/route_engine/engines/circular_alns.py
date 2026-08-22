import math
import random
import networkx as nx
from typing import List, Optional
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

_ALNS_ITERS = 200   # destroy/repair 반복 횟수
_MAX_STEPS = 400    # 초기 해 구성 최대 확장 횟수 (무한 루프 방지용 상한)
_SEG_MAX = 6        # destroy 시 한 번에 제거할 최대 노드 수
_DECAY = 0.8        # 연산자 가중치 감쇠 계수(과거:현재 반영 비율)
_W_MIN = 0.1        # 연산자 최소 가중치(가중치 0 방지)
_SIGMA1 = 3.0       # 보상: 전역 best 갱신
_SIGMA2 = 2.0       # 보상: 현재 해보다 개선
_SIGMA3 = 1.0       # 보상: 개악이지만 수용됨
_T0 = 1.0           # 시뮬레이티드 어닐링 초기 온도
_COOL = 0.995       # 온도 냉각 계수(반복마다 곱함)
_SEED = 42          # 난수 시드 고정 → 동일 입력이면 100% 동일 경로(재현성)


class CircularAlnsEngine:
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
        self._min_ratio    = 1.0  # find_path()가 실제 값으로 갱신함(A* 휴리스틱 스케일)

    def run(self) -> List[WalkRouteResponse]:
        """
        순환 경로를 생성합니다.
        """
        logger.info(
            "순환 ALNS 경로 생성 엔진을 시작합니다: target_km=%s, scoring_mode=%s, weights=%s",
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
            return [WalkRouteResponse(
                status=WalkRouteStatus.NO_NEAREST_START_NODE,
                mode=self.mode,
                coordinates=[],
                total_km=0.0,
            )]

        # 경로 생성
        nodes = self.find_path(start, self.inp.target_km or 3.0)

        # 경로가 없는 경우
        if not nodes:
            logger.warning("경로가 비어 있습니다.")
            return [WalkRouteResponse(
                status=WalkRouteStatus.NO_PATH,
                mode=self.mode,
                coordinates=[],
                total_km=0.0,
            )]

        pruned   = self.utils.prune_dead_ends(nodes)       # 왕복 가지 제거
        coords   = self.utils.extract_coordinates(pruned)  # [lat, lon] 좌표 목록
        total_m  = self.utils.calc_distance(pruned)        # 총 이동 거리(미터)
        total_km = round(total_m / 1000, 2)

        logger.info("경로 생성 완료: total_km=%.2f (target=%.2f), 노드=%d개",
                    total_km, self.inp.target_km or 3.0, len(nodes))

        return [WalkRouteResponse(
            status          = WalkRouteStatus.SUCCESS if coords else WalkRouteStatus.NO_PATH,
            mode            = self.mode,
            coordinates     = coords,
            total_km        = total_km,
        )]

    def find_path(self, start_node: int, target_km: float = 3.0) -> list[int]:
        """
        ALNS 기반 순환 경로를 생성합니다.
        """
        target_m = target_km * 1000  # 목표 거리를 미터 단위로 환산함
        rng = random.Random(self.seed)  # 엔진 전용 난수 인스턴스 → 재현성 보장
        # destroy/repair 재연결(_repair_shortest/_repair_detour)의 A* 휴리스틱 스케일용으로 캐싱함
        self._min_ratio = self.utils.min_cost_length_ratio(self.G)

        # 1단계: 출발지 → 반환점 (탐욕 구성)
        cost, nodes, dist, visited = self._find_start_to_waypoint(start_node, target_m)

        # 2단계: 반환점 → 출발지 (복귀 연결) → 초기 완성 해
        initial = self._find_waypoint_to_start(nodes, visited, start_node)
        if initial is None:
            logger.warning("ALNS 초기 해 구성에 실패해 출발 노드만 반환합니다.")
            return [start_node]

        # 3단계: destroy/repair 반복 개선
        best_path, best_key = self._improve(initial, start_node, target_m, rng)

        logger.info("ALNS 순환 경로 선택: 노드=%d개, 거리초과=%.0fm, 품질밀도=%.3f",
                    len(best_path), best_key[0], best_key[1])
        return best_path

    def _find_start_to_waypoint(self, start_node: int, target_m: float) -> tuple:
        """
        1단계: 출발지 → 반환점 경로를 생성합니다.
        """
        nodes   = [start_node]
        visited = {start_node}
        dist    = 0.0
        cost    = 0.0
        for _ in range(_MAX_STEPS):
            current    = nodes[-1]
            est_return = self.utils.est_network_dist(current, start_node)

            # 종료 판정: 누적거리 + 예상 복귀거리 ≥ 목표의 95% → 복귀 시점으로 간주
            # 누적 거리가 목표의 30%를 넘긴 뒤부터만 검사 → 너무 이른 종료 방지
            if dist > target_m * 0.3 and dist + est_return >= target_m * 0.95:
                break

            # 미방문 이웃 중 objective 최소(=가장 좋은) 노드를 탐욕적으로 선택(결정론)
            best_n, best_score, best_len, best_cost = None, None, None, None

            # 이웃을 node_id 오름차순으로 순회 → 결정론적 탐색 보장
            for n in sorted(self.G.neighbors(current)):
                if n in visited:
                    continue  # 이미 방문한 노드 제외
                
                edge      = self.G.get_edge_data(current, n) or {}
                step_cost = edge.get("custom_score", 1.0)
                step_len  = edge.get("length", 0)
                new_dist  = dist + step_len
                new_cost  = cost + step_cost
                score     = self.utils.objective(new_dist + self.utils.est_network_dist(n, start_node),
                                                 new_dist, new_cost, target_m)
                if best_score is None or (score, n) < (best_score, best_n):
                    best_n, best_score, best_len, best_cost = n, score, step_len, step_cost

            if best_n is None:
                break  # 모든 길이 막힌 경우 종료

            nodes.append(best_n)
            visited.add(best_n)
            dist += best_len
            cost += best_cost

        return cost, nodes, dist, visited

    def _find_waypoint_to_start(self, nodes: list[int], visited: set, start_node: int):
        """
        2단계: 반환점 → 출발지 경로를 생성합니다.
        """
        return self.utils.connect_to(nodes, visited, start_node)

    def _improve(self, initial: list[int], start_node: int, target_m: float, rng: random.Random) -> tuple:
        """
        3단계: destroy(구간 제거) + repair(재연결)를 반복하며 경로를 개선합니다.
        """
        destroy_ops = [self._destroy_random, self._destroy_worst]   # 제거 방법 2개
        repair_ops  = [self._repair_shortest, self._repair_detour]  # 재연결 방법 2개
        d_w = [1.0] * len(destroy_ops)  # 제거 방법별 가중치
        r_w = [1.0] * len(repair_ops)   # 재연결 방법별 가중치

        current,   cur_key  = initial, self.utils.route_key(initial, target_m)
        best_path, best_key = initial, cur_key
        temp = _T0

        for _ in range(_ALNS_ITERS):
            di = self._roulette(d_w, rng)  # 선택된 제거 방법 인덱스
            ri = self._roulette(r_w, rng)  # 선택된 재연결 방법 인덱스

            gap = destroy_ops[di](current, rng)          # (i, j) 제거 구간 or None
            if gap is None:
                temp *= _COOL
                continue
            candidate = repair_ops[ri](current, gap[0], gap[1], rng)  # 재연결된 새 경로 or None
            if candidate is None or len(candidate) < 2:
                temp *= _COOL
                continue

            candidate_key = self.utils.route_key(candidate, target_m)
            reward        = 0.0
            if candidate_key < best_key:
                best_path, best_key = candidate, candidate_key   # 전역 best 갱신
                current,   cur_key  = candidate, candidate_key
                reward = _SIGMA1
            elif candidate_key < cur_key:
                current, cur_key = candidate, candidate_key      # 현재 해 개선
                reward = _SIGMA2
            else:
                # 개악이라도 SA 확률로 수용 → 지역 최적 탈출
                delta = self._scalar(candidate_key) - self._scalar(cur_key)
                if delta <= 0 or rng.random() < math.exp(-delta / max(temp, 1e-9)):
                    current, cur_key = candidate, candidate_key
                    reward = _SIGMA3

            # 선택된 연산자 가중치 적응(감쇠 + 보상), 최소값 보장
            d_w[di] = max(_W_MIN, _DECAY * d_w[di] + (1 - _DECAY) * reward)
            r_w[ri] = max(_W_MIN, _DECAY * r_w[ri] + (1 - _DECAY) * reward)
            temp *= _COOL

        return best_path, best_key

    def _roulette(self, weights: list, rng: random.Random) -> int:
        """
        가중치를 기반으로 제거&재연결 메서드를 택합니다.
        : [제거] 구간 제거 or 최악 노드 제거
        : [재연결] 최단 경로 재연결 or 우회 재연결
        """
        r, acc = rng.random() * sum(weights), 0.0  # 화살이 떨어질 위치
        for i, w in enumerate(weights):
            acc += w
            if r <= acc:
                return i
        return len(weights) - 1

    def _scalar(self, key: tuple) -> float:
        """
        route_key 튜플을 스칼라로 환산합니다.
        """
        return key[0] * 1e6 + key[1]

    def _destroy_random(self, path: list[int], rng: random.Random):
        """
        무작위로 구간을 제거합니다.
        """
        if len(path) <= 3:
            return None
        i = rng.randint(1, len(path) - 2)  # 제거 구간 시작 인덱스
        seg = rng.randint(1, min(_SEG_MAX, len(path) - 1 - i))  # 제거 구간 길이
        return i, i + seg - 1  # (start, end)

    def _destroy_worst(self, path: list[int], rng: random.Random):
        """
        최악인 노드를 제거합니다.
        : 양옆 엣지 custom_score 합이 가장 큰 내부 노드를 제거 대상으로 지정합니다.
        """
        if len(path) <= 3:
            return None
        worst_i, worst_val = None, None
        for i in range(1, len(path) - 1):
            e1 = self.G.get_edge_data(path[i - 1], path[i]) or {}
            e2 = self.G.get_edge_data(path[i], path[i + 1]) or {}
            val = e1.get("custom_score", 1.0) + e2.get("custom_score", 1.0)
            if worst_val is None or val > worst_val:
                worst_val, worst_i = val, i
        return worst_i, worst_i

    def _repair_shortest(self, path: list[int], i: int, j: int, rng: random.Random):
        """
        노드를 최단 경로로 재연결합니다.
        """
        a_left, a_right = path[i - 1], path[j + 1]
        try:
            rec = self.utils.astar_path(a_left, a_right, weight="custom_score", min_ratio=self._min_ratio)
        except nx.NetworkXNoPath:
            return None
        return path[:i - 1] + rec + path[j + 2:]  # 접두부 + 재연결 + 접미부

    def _repair_detour(self, path: list[int], i: int, j: int, rng: random.Random):
        """
        노드를 우회하여 재연결합니다.
        """
        a_left, a_right = path[i - 1], path[j + 1]
        candidates = [v for v in sorted(self.G.neighbors(a_left)) if v != a_right]
        if not candidates:
            return self._repair_shortest(path, i, j, rng)
        m = rng.choice(candidates)  # 경유지 1개 택
        try:
            rec_tail = self.utils.astar_path(m, a_right, weight="custom_score", min_ratio=self._min_ratio)
        except nx.NetworkXNoPath:
            return self._repair_shortest(path, i, j, rng)
        rec = [a_left] + rec_tail  # aL → m → ... → aR
        return path[:i - 1] + rec + path[j + 2:]
