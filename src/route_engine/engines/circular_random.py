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

# 직선 거리 → 도로망 거리 추정 계수 (서울 도심 블록 구조 기준)
_NETWORK_FACTOR = 1.4

# ── beam search 설정값 ────────────────────────────────────────────────────────
_BEAM_WIDTH = 8                # 동시에 유지할 후보 경로(빔) 개수
_MAX_STEPS = 400              # 빔 확장 최대 반복 횟수 (무한 루프 방지용 상한)
_RETURN_REVISIT_PENALTY = 5.0  # 복귀 경로가 기방문 노드를 재사용할 때의 거리 가중 배수

# 거리 허용오차(m). |총거리 − target| 이 이 값 이내면 '거리 합격'으로 간주하고,
# 그 안에서는 품질(custom_score 밀도)이 더 좋은 경로를 택함. (계층적 목적함수)
_TOLERANCE_M = 0.1  # 10%


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
        
        pruned  = self.utils.prune_dead_ends(nodes)        # 왕복 가지 제거
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
        결정론적 beam search 기반 순환 경로 생성.

        설계 목표:
            ① target_km 근접  ② 왕복 가지 없음(단순 경로)  ③ 재현·설명 가능
            (동일 출발 노드 + target_km + 가중치 → 항상 동일 경로 보장. 랜덤 미사용)

        동작 개요:
            1단계 — 바깥으로 빔(후보 경로 _BEAM_WIDTH개)을 결정론적으로 확장함.
            2단계 — 각 후보를 출발점으로 닫은(복귀) 뒤, target_km 오차가 가장 작은 경로를 택함.
        """
        target_m = target_km * 1000  # 목표 거리를 미터 단위로 환산함

        # 출발 노드 좌표 — 추정 복귀거리 계산에 사용함
        s_data = self.G.nodes[start_node]
        s_lat  = s_data.get("lat", 0)  # 출발점 위도
        s_lon  = s_data.get("lon", 0)  # 출발점 경도

        def _est_return(node):
            """node에서 출발점까지의 추정 복귀거리(직선 × 도로망 계수)를 반환함."""
            d = self.G.nodes[node]
            straight = PathUtils._haversine_m(d.get("lat", s_lat), d.get("lon", s_lon), s_lat, s_lon)
            return straight * _NETWORK_FACTOR

        def _objective(value, dist, cost):
            """
            정렬용 키 튜플 (거리 합격 우선 → 그 안에서 품질)을 반환함.
              - over    : 허용오차(_TOLERANCE_M) 밖으로 벗어난 양(m). 0이면 '거리 합격'.
              - density : m당 평균 custom_score(=cost/거리). 낮을수록 고품질(길이 편향 제거).
            value=예상/최종 총거리(m), dist=품질평균 산정용 거리(m), cost=누적 custom_score.
            """
            over    = max(0.0, abs(value - target_m) - _TOLERANCE_M*target_m)
            density = cost / max(dist, 1.0)
            return (over, density)

        # 빔 1개의 구조: (누적_비용, 노드열, 누적_거리, 방문_노드_집합)
        #   - 누적_비용: 지나온 엣지들의 custom_score 합 (낮을수록 선호되는 경로임)
        #   - 방문_노드_집합: 노드 재방문 차단용 → 단순 경로 유지 → 왕복 가지 원천 차단
        beams = [(0.0, [start_node], 0.0, {start_node})]
        finished: list = []  # 복귀 시점에 도달한 빔들을 모으는 목록

        # ── 1단계: 빔을 바깥으로 결정론적으로 확장함 ────────────────────────────
        for _ in range(_MAX_STEPS):
            if not beams:
                break  # 더 확장할 빔이 없으면 종료함

            candidates: list = []  # 이번 스텝에서 생성된 모든 확장 후보를 담는 목록

            for cost, nodes, dist, visited in beams:
                current = nodes[-1]  # 해당 빔의 현재(마지막) 노드

                # 현재 위치 → 출발점 추정 복귀거리 (지금 돌아갈 때 들 거리)
                est_return = _est_return(current)

                # 종료 판정: (누적 + 추정복귀) ≥ 목표의 95% 이면 복귀 시점으로 간주함
                #   - 누적이 목표의 30%를 넘긴 뒤부터만 검사함 → 너무 이른 종료 방지
                if dist > target_m * 0.3 and dist + est_return >= target_m * 0.95:
                    finished.append((cost, nodes, dist, visited))
                    continue  # 이 빔은 확장 중단하고 복귀 후보로 보관함

                # 이웃을 node_id 오름차순으로 순회함 → 순서 고정(결정론의 핵심)
                for n in sorted(self.G.neighbors(current)):
                    if n in visited:
                        continue  # 이미 방문한 노드 제외 → 단순 경로 보장(왕복 가지 X)

                    edge      = self.G.get_edge_data(current, n) or {}
                    step_cost = edge.get("custom_score", 1.0)  # 엣지 비용(낮을수록 좋음)
                    step_len  = edge.get("length", 0)          # 엣지 실제 길이(미터)

                    # 확장된 새 빔 후보 생성 (집합은 복사해 빔마다 독립 상태 유지함)
                    candidates.append((
                        cost + step_cost,        # 누적 비용 갱신
                        nodes + [n],             # 노드열 확장
                        dist + step_len,         # 누적 거리 갱신
                        visited | {n},           # 방문 집합 확장
                    ))

            if not candidates:
                break  # 모든 빔이 막혔거나 모두 종료됨

            # 결정론적 상위 k 선별:
            #   (거리 합격 우선 → 그 안에서 품질밀도) 오름차순. 동점 시 노드열 사전순(결정론)
            #   예상총거리 = 누적거리 + 추정 복귀거리 / 품질밀도는 누적거리 기준
            candidates.sort(key=lambda b: _objective(b[2] + _est_return(b[1][-1]), b[2], b[0]) + (b[1],))
            beams = candidates[:_BEAM_WIDTH]  # 빔 폭만큼만 남기고 나머지 버림(탐색 효율)

        # 복귀 후보가 하나도 없으면(상한 도달 등) 마지막 빔들을 후보로 사용함
        pool = finished if finished else beams
        if not pool:
            logger.warning("beam search 후보가 비어 출발 노드만 반환합니다.")
            return [start_node]

        # ── 2단계: 각 후보를 출발점으로 닫고(복귀) 최종 경로를 평가·선택함 ───────
        best_path = None  # 최종 선택될 경로
        best_key  = None  # 비교용 정렬 키(작을수록 우수함)

        for cost, nodes, dist, visited in pool:
            # 복귀 가중치 함수: 기방문 노드 재사용 시 패널티 → 복귀 구간 중복(왕복) 억제함
            #   - 기본 인자 _visited로 현재 빔의 방문 집합을 묶음(루프 변수 늦은 바인딩 방지)
            def _return_weight(u, v, d, _visited=visited):
                penalty = _RETURN_REVISIT_PENALTY if (v in _visited and v != start_node) else 1.0
                return d.get("length", 1.0) * penalty

            try:
                ret = nx.shortest_path(self.G, nodes[-1], start_node, weight=_return_weight)
            except nx.NetworkXNoPath:
                continue  # 출발점으로 복귀 불가한 후보는 제외함

            # 복귀 구간 길이 합산 → 전체 경로 거리 산출함
            ret_len = sum(
                (self.G.get_edge_data(ret[i], ret[i + 1]) or {}).get("length", 0)
                for i in range(len(ret) - 1)
            )
            full_path = nodes + ret[1:]  # 바깥 경로 + 복귀 경로(시작 노드 중복 제거함)
            total_m   = dist + ret_len   # 전체 이동 거리

            # 전체 경로(복귀 포함)의 누적 custom_score → 품질밀도 산정에 사용함
            full_cost = sum(
                (self.G.get_edge_data(full_path[i], full_path[i + 1]) or {}).get("custom_score", 1.0)
                for i in range(len(full_path) - 1)
            )

            # 평가 키(작을수록 우수): (거리 합격 우선 → 그 안에서 품질) + 노드열 사전순(결정론)
            key = _objective(total_m, total_m, full_cost) + (tuple(full_path),)

            if best_key is None or key < best_key:
                best_key  = key
                best_path = full_path

        # 모든 후보가 복귀에 실패한 경우의 방어 코드
        if best_path is None:
            logger.warning("복귀 가능한 후보가 없어 첫 후보의 바깥 경로를 반환합니다.")
            return pool[0][1]

        logger.info("beam search 경로 선택: 노드=%d개, 거리초과=%.0fm, 품질밀도=%.3f",
                    len(best_path), best_key[0], best_key[1])
        return best_path
