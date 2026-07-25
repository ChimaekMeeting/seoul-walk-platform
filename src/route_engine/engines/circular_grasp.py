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
# PathUtils._TOLERANCE_RATIO(10%)의 2배. 결과가 이 이상 벗어나면 pool 전체가 부실했다고
# 보고 다른 seed로 재시도한다 (그 미만이면 정상 범위로 보고 재시도하지 않음).
_RETRY_OVER_RATIO = 0.1


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

        best_path, best_key = self._construct_best(start_node, target_m, self.seed)

        # 모든 후보가 복귀에 실패한 경우의 방어 코드
        if best_path is None:
            logger.warning("GRASP 후보가 비어 출발 노드만 반환합니다.")
            return [start_node]

        # 안전망: seed 하나의 난수열이 우연히 편향되면(예: 출발 구간이 계속 짧게
        # 끊겨서) pool 24개 전체가 부실하게 나올 수 있다 — 이 경우 VND(국소 탐색)만
        # 으로는 부족분을 못 메운다. 결과가 허용오차를 한참(2배 이상) 벗어났을 때만
        # 다른 seed로 통째로 한 번 더 구성해보고 더 나은 쪽을 채택한다. seed=42처럼
        # 이미 잘 나오는 경우는 이 조건에 안 걸려서 전혀 영향이 없다.
        total_m, cost = self.utils.metrics(best_path)
        over, _ = self.utils.objective(total_m, total_m, cost, target_m)
        if over > _RETRY_OVER_RATIO * target_m:  # 허용오차의 2배 이상 벗어난 경우만
            retry_path, retry_key = self._construct_best(start_node, target_m, self.seed + 1)
            if retry_path is not None and retry_key < best_key:
                logger.info("GRASP 1차 결과가 허용오차를 크게 벗어나 재시도 seed로 대체합니다.")
                best_path, best_key = retry_path, retry_key

        # 4단계: 가지치기(prune_dead_ends)가 구간을 잘라내며 접합면에 새 잔가시를
        # 만들 수 있어(경계 양쪽 노드가 우연히 같아지는 경우), 더 줄지 않을 때까지
        # 가지치기 ↔ 잔가시 제거를 번갈아 반복해 최종 경로를 마무리한다.
        best_path = self._finalize_path(best_path, target_m)

        logger.info("GRASP 순환 경로 선택: 노드=%d개, 거리초과=%.0fm, 품질밀도=%.3f",
                    len(best_path), best_key[0], best_key[1])
        return best_path

    def _construct_best(self, start_node: int, target_m: float, seed: int) -> tuple:
        """
        1~3단계: 지정된 seed로 pool을 구성하고, 반환 연결 + VND 개선까지 마친 뒤
        가장 좋은 완성 경로 1개를 (path, key)로 반환한다. 후보가 전혀 없으면
        (None, None).
        """
        rng = random.Random(seed)
        pool = self._build_pool(start_node, target_m, rng)

        best_path, best_key = None, None
        for cost, nodes, dist, visited in pool:
            closed = self._find_waypoint_to_start(nodes, visited, start_node)  # 2단계: 반환점 -> 출발지
            if closed is None:
                continue  # 복귀 불가한 해는 폐기
            improved = self._improve(closed, target_m)  # 3단계: VND 개선
            key = self.utils.route_key(improved, target_m)
            if best_key is None or key < best_key:
                best_key, best_path = key, improved
        return best_path, best_key

    def _finalize_path(self, path: list[int], target_m: float) -> list[int]:
        """
        prune_dead_ends와 VND 개선(_improve)을 번갈아 반복해 더 이상 변화가 없을
        때까지 경로를 정리한다.

        _improve()(잔가시 제거 + 노드 제거 + 우회 삽입 전체)를 다시 돌리는 이유:
        prune_dead_ends가 만든 새 잔가시를 _neighbor_collapse_spike로 제거하는 것에
        그치지 않고, 그렇게 줄어든 거리를 _neighbor_insert가 다른 길 우회로 보충할
        기회까지 함께 줘야 하기 때문이다.
        """
        while True:
            pruned = self.utils.prune_dead_ends(path)
            improved = self._improve(pruned, target_m)
            if improved == path:
                return improved
            path = improved

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
        3단계: 잔가시 제거 + 노드 제거 + 추가를 통해 경로를 개선합니다.
        """
        neighborhoods = [
            self._neighbor_collapse_spike, self._neighbor_remove,
            self._neighbor_insert, self._neighbor_detour,
        ]
        l = 0
        while l < len(neighborhoods):
            improved = neighborhoods[l](path, target_m)
            if improved is not None:
                path = improved
                l = 0        # 개선 시 첫 이웃으로 복귀(VNS 핵심)
            else:
                l += 1        # 개선 없으면 다음 이웃으로 전환
        return path

    def _neighbor_collapse_spike(self, path: list[int], target_m: float):
        """
        'A→B→A'처럼 갔다가 바로 되돌아오는 잔가시 구간(B)을 무조건 제거합니다.

        _neighbor_remove는 a==b(잔가시)인 경우를 명시적으로 건너뛴다 — "a와 b를
        직접 연결"이 a==b일 때는 의미가 없기 때문이다. 그래서 잔가시는 그 함수로는
        절대 제거되지 않고, prune_dead_ends(400m 미만만 정리)도 안 걸리는 왕복 구간은
        최종 경로에 그대로 남는다. 이 이웃이 그 빈틈을 메운다.

        다른 이웃 함수(_neighbor_remove/_neighbor_insert)와 달리 route_key 개선 여부로
        거르지 않고 발견 즉시 제거한다 — 잔가시는 "같은 길을 되짚어가는" 것 자체가
        거리 정확도와 무관하게 나쁜 모양이라고 보기 때문이다(순수 거리 기준으로만
        판정하면, 잔가시를 없앤 만큼 목표거리에서 멀어져 항상 기각된다).

        대신 제거로 줄어든 거리는 그 자리에서 한 번에 메우지 않는다. _improve()의 VND
        루프가 개선이 있을 때마다 처음 이웃(이 함수)부터 다시 도는 구조라, 이 함수가
        빈 자리를 만들면 다음 루프에서 _neighbor_insert가(한 번에 노드 하나씩, 여러
        번 반복) 되짚어가기가 아닌 진짜 다른 길로 우회 삽입해 거리를 다시 채운다.
        """
        for i in range(1, len(path) - 1):
            if path[i - 1] != path[i + 1]:
                continue
            candidate = path[:i] + path[i + 2:]
            if len(candidate) < 2:
                continue
            return candidate
        return None  # 잔가시가 없으면 None 반환

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

    def _neighbor_detour(self, path: list[int], target_m: float):
        """
        인접한 두 경로 노드(a, b) 사이를, 아직 경로에 없는 새 노드 2개(x1, x2)를
        거치는 3홉 우회로 — a→x1→x2→b — 로 대체합니다.

        _neighbor_insert는 a와 b의 '공통 이웃' 1개만 끼워넣을 수 있어서, 공통 이웃이
        없는 지점(예: circular_23처럼 막다른 구간 근처)에서는 우회 자체를 못 찾는다.
        이 이웃은 한 단계 더 나가서, a에서 출발해 완전히 새로운 길 2개를 거쳐 b로
        돌아오는 경로를 찾아 우회 가능 지점을 넓힌다. (되짚어가는 게 아니라 매번
        새 노드만 거치므로 잔가시/왕복겹침을 새로 만들지 않는다.)

        최후의 수단으로만 동작한다: 현재 경로가 이미 목표거리 허용 오차(±10%) 이내면
        아무것도 하지 않고 바로 None을 반환한다. 허용 오차 안에 든 경로까지 이 이동으로
        건드리면, VND가 "허용 오차 안에서는 다 똑같이 좋다"는 판정 기준(objective의
        over=0) 때문에 오차 안에서 정밀도를 계속 갉아먹으며 표류할 수 있다 — 이미
        멀쩡한 시나리오까지 탐색 궤적이 흔들리는 부작용을 막기 위한 가드다.
        """
        total_m, cost = self.utils.metrics(path)
        over, _ = self.utils.objective(total_m, total_m, cost, target_m)
        if over <= 0.0:
            return None  # 이미 허용 오차 이내면 손대지 않음

        in_path = set(path)
        best_path, best_key = None, self.utils.route_key(path, target_m)
        for i in range(len(path) - 1):
            a, b = path[i], path[i + 1]
            for x1 in sorted(self.G.neighbors(a)):
                if x1 in in_path:
                    continue
                for x2 in sorted(self.G.neighbors(x1)):
                    if x2 in in_path or x2 == a or not self.G.has_edge(x2, b):
                        continue
                    candidate = path[:i + 1] + [x1, x2] + path[i + 1:]
                    key = self.utils.route_key(candidate, target_m)
                    if key < best_key:
                        best_key, best_path = key, candidate
        return best_path  # 개선되지 않았으면 None 반환