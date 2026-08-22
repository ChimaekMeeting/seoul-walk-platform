"""
src/route_engine/engines/oneway_plateau.py

Plateau method 기반 우회 편도(oneway_random) 경로 생성 엔진.

알고리즘 개요:
1. 출발지 기준 정방향 Dijkstra 트리, 도착지 기준 역방향 Dijkstra 트리를 각 1회 계산
   (nx.single_source_dijkstra 재활용 — OnewayDijkstraEngine과 동일한 최단경로 로직)
2. 두 트리 모두에 도달 가능한 모든 노드를 "우회 지점(via-node)" 후보로 취급
3. 각 후보를 (목표거리 근접도 → 베이스 최단경로와의 중복 구간 비율="plateau" → 품질밀도)
   3단계 기준으로 정렬해 최적 1개를 선택함. 베이스 최단경로를 그대로 따르는 구간(plateau)이
   적을수록 우선순위가 높아짐 — 이 알고리즘의 핵심 차별점.

알고리즘 특징:
- 다른 메타휴리스틱(GRASP/ALNS)과 달리 반복/폭 튜닝이 필요 없는 결정론적 O(N) 알고리즘
- 생성자(__init__)와 run() 흐름은 oneway_beam.py/oneway_rcsp.py 등과 동일한 뼈대를 그대로 사용함
  (PathUtils, calculate_custom_score, 실패 status 처리, prune_dead_ends → 좌표 변환 순서)
- circular(순환) 경로에는 적용 불가: 정방향/역방향 트리 구조가 출발=도착인 순환 경로와 맞지 않음
"""


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
from src.schema.route_schema import OnewayRouteInput, Weights
from src.route_engine.scoring.scoring_engine import calculate_custom_score

logger = logging.getLogger(__name__)


class OnewayPlateauEngine:
    """
    정방향(출발지) Dijkstra 트리 + 역방향(도착지) Dijkstra 트리를 각각 1회씩 구한 뒤,
    두 트리가 공유하는 "plateau"(베이스 최단경로와 겹치는 구간)를 최소화하는
    via-node를 골라 우회 편도 경로를 만드는 엔진입니다.
    반복/폭 튜닝이 필요한 다른 엔진과 달리 결정론적 O(N) 알고리즘이라 별도 상수가 없습니다.
    """

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
        logger.info(f"랜덤 편도 Plateau 경로 생성 엔진을 시작합니다: target_km={self.inp.target_km}, scoring_mode={self.scoring_mode}, weights={self.weights}")

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

        # 경로 생성
        nodes = self.find_path(start, end, self.inp.target_km or 3.0)

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
        total_m  = self.utils.calc_distance(pruned)        # 총 이동 거리(m)
        total_km = round(total_m / 1000, 2)

        logger.info(f"total_km: {total_km}")

        return [WalkRouteResponse(
            status          = WalkRouteStatus.SUCCESS if coords else WalkRouteStatus.NO_PATH,
            mode            = self.mode,
            coordinates     = coords,
            total_km        = total_km,
        )]

    def find_path(self, start: int, end: int, target_km: float = 3.0) -> list[int]:
        """
        Plateau method 기반 우회 편도 경로를 생성합니다.
        """
        target_m = target_km * 1000  # 목표 거리를 미터로 환산함

        # 1단계: 정방향 트리(출발지 기준) — 전체 도달 가능 노드의 (누적비용, 노드열)
        fwd_cost, fwd_path = nx.single_source_dijkstra(self.G, start, weight="custom_score")

        if end not in fwd_path:
            logger.warning("출발-도착 간 경로가 존재하지 않습니다.")
            return []

        base_path = fwd_path[end]  # 베이스 최단경로 — Dijkstra 엔진과 동일한 결과

        # 2단계: 역방향 트리(도착지 기준) — directed 그래프는 reverse view 위에서 탐색
        G_bwd = self.G.reverse(copy=False) if self.G.is_directed() else self.G
        bwd_cost, bwd_path = nx.single_source_dijkstra(G_bwd, end, weight="custom_score")

        # 3단계: 베이스 최단경로의 엣지 집합 — "plateau"(중복 구간) 판별 기준
        base_edges = {
            frozenset((base_path[i], base_path[i + 1]))
            for i in range(len(base_path) - 1)
        }

        # 4단계: 두 트리의 실제 거리(m)와 베이스 경로 중복거리(m)를 같은 순회에서 함께 누적 — O(N)
        fwd_len, fwd_overlap = self._cumulative_len_and_overlap(self.G, fwd_cost, fwd_path, start, base_edges)
        bwd_len, bwd_overlap = self._cumulative_len_and_overlap(G_bwd,   bwd_cost, bwd_path, end,   base_edges)

        # 5단계: 두 트리에 모두 존재하는 노드를 via-node 후보로 평가 (경로 조립 없이 누적값만 비교)
        best_v, best_key = None, None
        for v in set(fwd_path) & set(bwd_path):
            total_len  = fwd_len[v] + bwd_len[v]
            total_cost = fwd_cost[v] + bwd_cost[v]
            if total_len <= 0:
                continue  # 출발=도착=v인 퇴화 케이스 제외

            over, density = self.utils.objective(total_len, total_len, total_cost, target_m)
            overlap_ratio  = (fwd_overlap[v] + bwd_overlap[v]) / max(total_len, 1.0)

            # (거리 목표 충족 우선 → plateau 중복 적은 순 → 품질밀도) 결정론적 정렬 키
            key = (over, overlap_ratio, density)
            if best_key is None or key < best_key:
                best_key, best_v = key, v

        if best_v is None:
            logger.warning("Plateau 후보가 비어 최단 경로로 대체합니다.")
            return base_path

        # 최종 선택된 1개 노드에 대해서만 실제 경로를 조립함
        best_path = self._build_candidate(fwd_path[best_v], bwd_path[best_v])

        logger.info("Plateau 편도 경로 선택: 노드=%d개, 거리초과=%.0fm, 중복비율=%.3f, 품질밀도=%.3f",
                    len(best_path), best_key[0], best_key[1], best_key[2])
        return best_path

    def _cumulative_len_and_overlap(
        self, G: nx.Graph, cost: dict, path: dict, source: int, base_edges: set
    ) -> tuple[dict, dict]:
        """
        Dijkstra 트리(cost/path)를 비용 오름차순으로 순회하며 실제 거리(m) 누적값과
        베이스 최단경로(base_edges)와 겹치는 구간의 누적 거리(m)를 함께 계산합니다.
        예측 노드가 항상 먼저 처리되도록 비용 오름차순 순서를 이용함(음수 없는 트리의 성질).
        """
        length, overlap = {source: 0.0}, {source: 0.0}
        for v in sorted(cost, key=cost.get):
            if v == source:
                continue
            pred = path[v][-2]
            edge = G.get_edge_data(pred, v) or {}
            edge_len = edge.get("length", 0)
            length[v] = length[pred] + edge_len
            overlap[v] = overlap[pred] + (edge_len if frozenset((pred, v)) in base_edges else 0.0)
        return length, overlap

    def _build_candidate(self, fwd: list[int], bwd: list[int]) -> list[int]:
        """
        정방향 경로(출발지→v)와 역방향 경로(도착지→v)를 이어 붙여 전체 경로를 만듭니다.
        bwd는 [도착지, ..., v] 순서이므로 뒤집으면 [v, ..., 도착지]가 됨.
        """
        tail = list(reversed(bwd))
        return fwd + tail[1:]