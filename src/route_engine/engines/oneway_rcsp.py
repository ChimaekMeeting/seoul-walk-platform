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

_MAX_STEPS = 400      # 라벨 확장 최대 반복 횟수 (무한 루프 방지용 상한)
_LABEL_CAP = 4        # 노드 1개당 유지할 파레토 라벨 최대 개수
_FRONTIER_CAP = 64    # 스텝당 확장 프런티어 라벨 최대 개수 (결정론적 상한)
_POOL_CAP = 16        # 도착 후보 풀 최대 개수
_UPPER_RATIO = 1.1    # 자원(거리) 상한 = 목표 × 1.1 (이 값을 넘는 라벨은 폐기)


class OnewayRcspEngine:
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

    def run(self) -> WalkRouteResponse:
        """
        우회 편도 경로를 생성합니다.
        """
        logger.info(f"랜덤 편도 RCSP 경로 생성 엔진을 시작합니다: target_km={self.inp.target_km}, scoring_mode={self.scoring_mode}, weights={self.weights}")

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
        nodes = self.find_path(start, end, self.inp.target_km or 3.0)

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
        total_m  = self.utils.calc_distance(pruned)        # 총 이동 거리(m)
        total_km = round(total_m / 1000, 2)

        logger.info(f"total_km: {total_km}")

        return WalkRouteResponse(
            status          = WalkRouteStatus.SUCCESS if coords else WalkRouteStatus.NO_PATH,
            mode            = self.mode,
            coordinates     = coords,
            total_km        = total_km,
        )

    def find_path(self, start: int, end: int, target_km: float = 3.0) -> list[int]:
        """
        RCSP 기반 우회 편도 경로를 생성합니다.
        """
        target_m = target_km * 1000  # 목표 거리를 미터로 환산함

        # custom_score 기준 최단경로 — 후보 미발견/불가 시의 최종 대체 경로로도 사용함
        try:
            base_shortest = nx.shortest_path(self.G, start, end, weight="custom_score")
        except nx.NetworkXNoPath:
            logger.warning("출발-도착 간 경로가 존재하지 않습니다.")
            return []

        # 1단계: 출발지 → 도착 후보 (라벨 전파)
        labels = self._find_start_to_waypoint(start, end, target_m)

        # 1.5단계: 도착 후보 풀 구성
        pool = self._build_pool(labels)
        if not pool:
            logger.warning("RCSP 도착 후보가 비어 최단 경로로 대체합니다.")
            return base_shortest

        # 2단계: 중간지점 → 도착지 (도착 연결 후 가장 좋은 완성 경로 1개 선택)
        best_path, best_key = None, None
        for cost, nodes, dist, visited in pool:
            closed = self._find_waypoint_to_end(nodes, visited, end)
            if closed is None:
                continue  # 도착 연결 불가 후보는 제외
            key = self.utils.route_key(closed, target_m)
            if best_key is None or key < best_key:
                best_key, best_path = key, closed

        # 모든 후보가 도착 연결에 실패한 경우의 방어 코드
        if best_path is None:
            logger.warning("도착 연결 가능한 후보가 없어 최단 경로로 대체합니다.")
            return base_shortest

        logger.info("RCSP 편도 경로 선택: 노드=%d개, 거리초과=%.0fm, 품질밀도=%.3f",
                    len(best_path), best_key[0], best_key[1])
        return best_path
    
    def _prune_labels(self, labels: list) -> list:
        """
        확장 라벨들을 노드별 파레토 최적만 남기고 상위 N개만을 추출합니다.
        """
        by_node: dict = {}
        for lb in labels:
            by_node.setdefault(lb[2][-1], []).append(lb)

        kept: list = []
        for _, ls in by_node.items():
            ls.sort(key=lambda lb: (lb[0], lb[1], lb[2]))  # (비용,거리,경로) 결정론적 정렬
            pareto: list = []
            for lb in ls:
                # 이미 (비용,거리) 모두 우수한 라벨이 있으면 지배당함 → 제외
                if any(o[0] <= lb[0] and o[1] <= lb[1] for o in pareto):
                    continue
                pareto.append(lb)
            kept.extend(pareto[:_LABEL_CAP])

        kept.sort(key=lambda lb: (lb[0], lb[1], lb[2]))
        return kept[:_FRONTIER_CAP]

    def _find_start_to_waypoint(self, start: int, end: int, target_m: float) -> list:
        """
        1단계: 출발지 → 중간지점 경로를 생성합니다.
        """
        upper = target_m * _UPPER_RATIO  # 자원(거리) 상한
        frontier = [(0.0, 0.0, (start,))]  # 초기 라벨
        arrived: list = []

        for _ in range(_MAX_STEPS):
            if not frontier:
                break

            candidates: list = []
            for cost, dist, path in frontier:
                u = path[-1]

                # 도착지에 닿았으면 도착 후보로 확정 (누적거리가 목표의 30% 이상일 때만)
                if u == end and dist > target_m * 0.3:
                    arrived.append((cost, dist, path))
                    continue  # 도착 라벨은 확장 중단

                # 이웃을 node_id 오름차순으로 순회 → 결정론적 전파
                for v in sorted(self.G.neighbors(u)):
                    if v in path:
                        continue  # 단순 경로 유지(재방문 금지)
                    edge = self.G.get_edge_data(u, v) or {}
                    nd   = dist + edge.get("length", 0)
                    if nd > upper:
                        continue  # 자원(거리) 상한 초과 → 폐기
                    nc = cost + edge.get("custom_score", 1.0)
                    candidates.append((nc, nd, path + (v,)))

            frontier = self._prune_labels(candidates)  # 파레토 + 상한 가지치기

        return arrived

    def _build_pool(self, labels: list) -> list:
        """
        1.5단계: 반환 후보 풀을 구성합니다.
        """
        labels.sort(key=lambda lb: (lb[0], lb[1], lb[2]))  # 결정론적 순서
        pool: list = []
        seen: set = set()
        for cost, dist, path in labels:
            if path in seen:
                continue  # 동일 경로 중복 제거
            seen.add(path)
            pool.append((cost, list(path), dist, set(path)))  # beam과 동일한 형식
            if len(pool) >= _POOL_CAP:
                break
        return pool

    def _find_waypoint_to_end(self, nodes: list[int], visited: set, end: int):
        """
        2단계: 한 후보의 중간지점 → 도착지 경로를 생성합니다.
        """
        return self.utils.connect_to(nodes, visited, end)
