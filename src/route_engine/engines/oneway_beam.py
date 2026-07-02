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

# 직선 거리 → 도로망 거리 추정 계수 (서울 도심 블록 구조 기준)
_NETWORK_FACTOR = 1.4

# ── beam search 설정값 ────────────────────────────────────────────────────────
_BEAM_WIDTH = 8                # 동시에 유지할 후보 경로(빔) 개수
_MAX_STEPS = 400               # 빔 확장 최대 반복 횟수 (무한 루프 방지용 상한)
_RETURN_REVISIT_PENALTY = 5.0  # 도착 연결 시 기방문 노드 재사용 억제 배수

_TOLERANCE_RATIO = 0.1         # 허용 오차 범위 10%

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

    def run(self) -> WalkRouteResponse:
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

        pruned  = self.utils.prune_dead_ends(nodes)        # 왕복 가지 제거
        coords  = self.utils.extract_coordinates(pruned)  # [lat, lon] 좌표 목록
        total_m = self.utils.calc_distance(pruned)        # 총 이동 거리(m)
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
        beam search를 기반으로 우회 편도 경로를 생성합니다.
        """
        target_m = target_km * 1000  # 목표 거리를 미터로 환산함

        # custom_score 기준 최단경로 — 우회 실패/불가 시의 최종 대체 경로로도 사용함
        try:
            base_shortest = nx.shortest_path(self.G, start, end, weight="custom_score")
        except nx.NetworkXNoPath:
            logger.warning("출발-도착 간 경로가 존재하지 않습니다.")
            return []

        # 실제 거리(length) 기준 최단경로가 이미 목표 이상이면 우회 불필요 → 그대로 반환함
        try:
            shortest_by_length = nx.shortest_path(self.G, start, end, weight="length")
            min_dist_m = self.utils.calc_distance(shortest_by_length)
        except nx.NetworkXNoPath:
            min_dist_m = self.utils.calc_distance(base_shortest)
        if min_dist_m >= target_m:
            logger.info("최단 경로가 이미 목표 거리 이상이므로 우회 없이 반환합니다.")
            return base_shortest

        # 도착 노드 좌표 — 목적지까지 남은 거리 추정에 사용함
        e_data = self.G.nodes[end]
        e_lat  = e_data.get("lat", 0)  # 도착점 위도
        e_lon  = e_data.get("lon", 0)  # 도착점 경도

        def _est_to_end(node):
            """
            node에서 도착점까지의 예상 거리(직선 × 도로망 계수)를 반환
            """
            d = self.G.nodes[node]
            straight = PathUtils._haversine_m(d.get("lat", e_lat), d.get("lon", e_lon), e_lat, e_lon)
            return straight * _NETWORK_FACTOR

        def _objective(value, dist, cost):
            """
            정렬용 키 튜플 (거리 합격 우선 → 그 안에서 품질)을 반환
            """
            over    = max(0.0, abs(value - target_m) - _TOLERANCE_RATIO*target_m)  # |실제 오차| - 허용 오차
            density = cost / max(dist, 1.0) # 품질
            return (over, density)

        # 빔 1개의 구조: (누적_비용, 노드열, 누적_거리, 방문_노드_집합)
        beams = [(0.0, [start], 0.0, {start})]
        finished: list = []  # 도착에 닿았거나 연결 시점에 도달한 빔을 모으는 목록

        # 1단계: 출발지 -> 중간 지점
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

                # 현재 → 도착점 추정 남은거리
                est_to_end = _est_to_end(current)

                # 종료 판정: 누적거리 + 도착점까지의 예상 거리 ≥ 목표의 95% -> 도착점으로 나아가야 할 시점으로 간주
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

            # 결정론적 상위 k 선별
            # _est_return(현재 노드) -> 출발지까지의 예상 복귀 거리 
            # _objective(실제 이동 거리 + 출발점까지의 예상 복귀 거리, 실제 이동 거리, 누적 비용) ->  (|실제 오차| - 허용 오차, 품질)
            # b = (누적 비용, 노드열, 누적 거리, 방문 집합)
            candidates.sort(key=lambda b: _objective(b[2] + _est_to_end(b[1][-1]), b[2], b[0]) + (b[1],))
            beams = candidates[:_BEAM_WIDTH]

        # 후보가 하나도 없으면(상한 도달 등) 마지막 빔들을 후보로 사용함
        pool = finished if finished else beams
        if not pool:
            logger.warning("beam search 후보가 비어 최단 경로로 대체합니다.")
            return base_shortest

        # 2단계: 중간 지점 -> 목적지
        best_path = None  # 최종 선택될 경로
        best_key  = None  # 비교용 정렬 키(작을수록 우수함)

        for cost, nodes, dist, visited in pool:
            if nodes[-1] == end:
                full_path = nodes  # 이미 도착에 닿은 경로
                total_m   = dist
            else:
                # 도착 연결: 현재 → 도착 최단경로. 기방문 노드 재사용에 패널티 → 중복 억제함
                #   - 기본 인자 _visited로 현재 빔의 방문 집합을 묶음(루프 변수 늦은 바인딩 방지)
                def _tail_weight(u, v, d, _visited=visited):
                    penalty = _RETURN_REVISIT_PENALTY if (v in _visited and v != end) else 1.0
                    return d.get("length", 1.0) * penalty
                try:
                    tail = nx.shortest_path(self.G, nodes[-1], end, weight=_tail_weight)
                except nx.NetworkXNoPath:
                    continue  # 도착 연결 불가 후보는 제외함

                tail_len = sum(
                    (self.G.get_edge_data(tail[i], tail[i + 1]) or {}).get("length", 0)
                    for i in range(len(tail) - 1)
                )
                full_path = nodes + tail[1:]  # 바깥 경로 + 도착 연결 경로(중복 노드 제거함)
                total_m   = dist + tail_len

            # 전체 경로(도착 연결 포함)의 누적 custom_score → 품질밀도 산정에 사용함
            full_cost = sum(
                (self.G.get_edge_data(full_path[i], full_path[i + 1]) or {}).get("custom_score", 1.0)
                for i in range(len(full_path) - 1)
            )

            # 평가 키(작을수록 우수): (|실제 오차| - 허용 요차, 품질) + 노드열 사전순(결정론)
            key = _objective(total_m, total_m, full_cost) + (tuple(full_path),)
            if best_key is None or key < best_key:
                best_key  = key
                best_path = full_path

        # 모든 후보가 도착 연결에 실패한 경우의 방어 코드
        if best_path is None:
            logger.warning("도착 연결 가능한 후보가 없어 최단 경로로 대체합니다.")
            return base_shortest

        logger.info("beam search 편도 경로 선택: 노드=%d개, 거리초과=%.0fm, 품질밀도=%.3f",
                    len(best_path), best_key[0], best_key[1])
        return best_path