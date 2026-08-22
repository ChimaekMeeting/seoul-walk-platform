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
from src.route_engine.scoring.scoring_engine import calculate_custom_score, compute_score_vector

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
        visited_nodes: Optional[set] = None,
    ):
        self.inp           = inp
        self.G             = G.copy()  # 원본 그래프 보호
        self.utils         = PathUtils(self.G)
        self.mode          = WalkMode.ONEWAY_RANDOM
        profile_config     = get_profile(profile)
        self.weights       = merge_weights(profile_config.weights, custom_weights)
        self.blocked_tags  = profile_config.blocked_tags
        self.scoring_mode  = profile_config.scoring_mode
        # WaypointComposerEngine이 leg 간 경로 겹침을 페널티로 방지할 때 채워줌. 기본(빈 set)이면 기존 동작과 동일.
        self.visited_nodes = visited_nodes or set()
        self.last_path_nodes: list[int] = []  # 후보 1(run()[0])의 노드열(왕복 가지 제거 후) — 하위 호환용 단축 값
        self.last_path_nodes_by_candidate: list[list[int]] = []  # run()이 반환한 모든 후보의 노드열(반환 순서와 동일)

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

        # find_path()가 최대 3개까지 다양화한 후보를 반환함 — 각각을 응답으로 변환
        responses: List[WalkRouteResponse] = []
        for i, nodes in enumerate(candidates):
            pruned = self.utils.prune_dead_ends(nodes)  # 왕복 가지 제거
            # 반환하는 모든 후보의 노드열을 인덱스별로 보관 — WalkRouteResponse에는
            # 좌표만 있고 노드 ID가 없어서, 나중에 호출자가 후보 1이 아닌 다른 후보를
            # 선택하더라도(예: WaypointComposerEngine이 leg 선택 로직을 바꾸는 경우)
            # 그 후보의 실제 노드열을 되찾을 수 있게 하기 위함.
            self.last_path_nodes_by_candidate.append(pruned)
            if i == 0:
                # 하위 호환용 — 지금의 WaypointComposerEngine은 항상 후보 1(run()[0])만
                # 쓰므로 last_path_nodes는 그 경우를 위한 단축 값이다.
                self.last_path_nodes = pruned
            coords   = self.utils.extract_coordinates(pruned)  # [lat, lon] 좌표 목록
            total_m  = self.utils.calc_distance(pruned)        # 총 이동 거리(m)
            total_km = round(total_m / 1000, 2)
            responses.append(WalkRouteResponse(
                status          = WalkRouteStatus.SUCCESS if coords else WalkRouteStatus.NO_PATH,
                mode            = self.mode,
                coordinates     = coords,
                total_km        = total_km,
            ))

        logger.info(f"생성된 후보 수: {len(responses)}, total_km: {[r.total_km for r in responses]}")

        return responses

    def find_path(self, start: int, end: int, target_km: float = 3.0) -> list[list[int]]:
        """
        beam search 기반 우회 편도 경로를 생성합니다.
        """
        target_m = target_km * 1000  # 목표 거리를 미터로 환산함

        # custom_score 기준 최단경로 — 우회 실패/불가 시의 최종 대체 경로로도 사용함
        min_ratio = self.utils.min_cost_length_ratio(self.G)
        try:
            base_shortest = self.utils.astar_path(start, end, weight="custom_score", min_ratio=min_ratio)
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

        # 2단계: 중간지점 → 도착지 연결에 성공한 완성 후보를 모두 모은다
        closed_candidates: list[tuple[tuple, list[int]]] = []  # [(key, path), ...]
        for cost, nodes, dist, visited in pool:
            closed = self._find_waypoint_to_end(nodes, visited, end)
            if closed is None:
                continue  # 도착 연결 불가 후보는 제외함
            over, density, path_tuple = self.utils.route_key(closed, target_m)
            overlap = self._overlap_ratio(closed, base_edges)
            key = (over, overlap, density, path_tuple)  # 거리 합격 → 우회도 → 품질밀도 순으로 비교
            closed_candidates.append((key, closed))

        # 모든 후보가 도착 연결에 실패한 경우의 방어 코드
        if not closed_candidates:
            logger.warning("도착 연결 가능한 후보가 없어 최단 경로로 대체합니다.")
            return [base_shortest]

        # 후보 1: 기존과 동일하게 (거리 합격 → 우회도 → 품질밀도) 기준 최상위
        closed_candidates.sort(key=lambda item: item[0])
        best_key, best_path = closed_candidates[0]
        logger.info("beam search 편도 경로 선택(대표): 노드=%d개, 거리초과=%.0fm, 우회도=%.3f, 품질밀도=%.3f",
                    len(best_path), best_key[0], best_key[1], best_key[2])

        # 후보 2·3: 대표와 같은 거리 등급(over)을 만족하는 후보들 안에서만
        # safety/nature/slope/convenience/accessibility 벡터로 다양화한다.
        # (over가 0.0으로 정확히 겹치는 경우가 흔해 그룹핑 기준으로 안전하지만,
        #  overlap/density는 연속값이라 정확히 안 겹칠 수 있어 기준에서 제외한다.)
        qualifying = [(key, path) for key, path in closed_candidates if key[0] == best_key[0]]

        vector_lookup = compute_score_vector(self.G)
        diversity_candidates = [
            (self.utils.path_score_vector(path, vector_lookup), path)
            for _, path in qualifying
        ]
        return self.utils.select_diverse_paths(diversity_candidates, k=3)


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
                    step_cost = edge.get("custom_score", 1.0)
                    # leg 간 경로 겹침 방지: 다른 leg가 이미 지나간 노드면 페널티(도착지 자신은 제외)
                    if n in self.visited_nodes and n != end:
                        step_cost *= _RETURN_REVISIT_PENALTY
                    candidates.append((
                        cost + step_cost,                      # 누적 비용 갱신
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
        leg 간 경로 겹침 방지를 위해 이 leg 내부 visited에 다른 leg의 visited_nodes도 합쳐서 넘긴다.
        """
        return self.utils.connect_to(nodes, visited | self.visited_nodes, end)