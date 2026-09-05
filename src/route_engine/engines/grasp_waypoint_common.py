"""
src/route_engine/engines/grasp_waypoint_common.py

경유지(waypoint) 선택 기반 GRASP 계열 엔진(local/VND/VNS/ALNS, circular_grasp_waypoint_*.py)이
공유하는 순수 로직. GRASP은 여기서 전체 경로를 직접 만들지 않고 경유지 cfg.num_waypoints개만
선택하며, 실제 구간 연결(p1→w1→...→w_N→p1)은 NetworkX A*(PathUtils.astar_path 경유)가 담당한다.

경유지 개수 n 일반화(2026-09-02, "GRASP 경유지 개수를 임의 n으로 확장" 이슈):
    이전 버전은 경유지가 정확히 2개(p2, p3)라는 전제가 Route 데이터 모델(waypoint2/waypoint3
    필드)부터 랭킹 함수(_rank_p2_candidates/_rank_p3_candidates)까지 하드코딩돼 있었다.
    Route.waypoints: list[int]와 _rank_next_waypoint_candidates() 하나로 통합해 임의
    개수로 확장했다. GraspConfig.num_waypoints=2가 기본값이라 기존 호출부(모두 이 기본값을
    씀)는 동작이 완전히 동일하게 유지된다.

    랭킹 함수는 항상 "직전에 고른 경유지(prev)" 기준으로 다음 후보를 평가한다 — 매 단계
    p1 기준으로 고정해 랭킹하면 각 단계가 서로 독립적인 샘플링이 되어버려, 경유지가
    늘어날수록 GRASP 특유의 적응적 그리디 구축(직전 선택을 반영해 다음 그리디 점수를
    다시 계산)이 무력화된다. prev==p1(첫 경유지를 고르는 단계)일 때는 비교할 '직전 방향'이
    없으므로 기존 _rank_p2_candidates와 동일하게 방향 다양성 페널티 없이 순수 거리
    적합도만 쓴다 — 이 경우 공식이 |2·dist(p1,c) − target_m|로 자동 축약되어 기존 동작과
    완전히 같아진다(_rank_next_waypoint_candidates 문서 참고).

경유지 후보는 waypoint_pool.py::WaypointPoolGenerator/WaypointPoolResult를 그대로 쓴다
(p1 기준 cutoff SSSP 단일 풀 + lazy 거리 캐시, r_max=target_m/2 — 논문 근거는
waypoint_pool.py 모듈 docstring 참고, r_max 부등식 자체가 경유지 개수 n과 무관하게
성립함도 그 문서에 명시돼 있다). 이전에 이 파일에 직접 구현했던 Haversine 사전필터
기반 거리링(GenerateDistanceRing)·2링 접근은 전부 제거했다 — waypoint_pool.py가 같은
문제(대형 그래프에서 후보-거리 계산 비용)를 논문 근거가 있는 방식으로 이미 풀어뒀다.

기존 circular_grasp.py(엣지 단위로 전체 경로를 직접 구성하는 방식)와는 알고리즘 구조가
다른 별도 비교용 구현이며, 그 파일과 grasp_solver.py는 이 작업으로 수정하지 않는다.

거리 속성명 확정:
    이 프로젝트의 실제 거리 엣지 속성명은 length이다. (DB/엔티티 컬럼명은 length_m이지만,
    graph_repository.py::_edge_attributes()가 "length": row.length_m으로 매핑하고,
    기존 PathUtils도 전부 data.get("length", ...)를 쓴다.) 모든 거리 비용과 경로 길이
    계산은 이 속성을 기준으로 한다.

향후 자연/안전 점수 모드(mode="natural" / "distance_natural") 활성화 순서
(현재는 전부 비활성 — 아래 EdgeCost() 참고, 임의로 앞당기지 말 것):
    1. 도보 데이터의 nature_score 정의(방향·정규화) 확인
    2. walk_edge.py의 nature_score 엔티티 매핑 복구
    3. graph_repository.py에서 엣지 속성으로 로드
    4. 그래프의 각 엣지에 nature_score가 실제로 존재하는지 검증
    5. EdgeCost("natural")의 점수→비용 변환 정책 구현
       (점수가 높을수록 좋은지 낮을수록 좋은지에 따라 변환 방향이 달라지므로 임의 결정 금지)
    6. A*의 weight 함수(_CostCache._weight)에 동일한 mode 전달 확인
    7. GRASP·VND·VNS·최종 평가 전체에서 동일한 비용 정책 사용 확인
       (단, waypoint_pool.py의 풀 생성 자체는 compute_distance_only_lookup에 고정돼 있어
       mode="natural"을 켜더라도 풀 생성까지 자동으로 따라가지 않는다 — 그 경우 풀 생성
       쪽도 별도로 확장해야 한다는 점을 활성화 시점에 재확인할 것)
    8. 자연 모드 전용 테스트와 벤치마크 실행

    Route/BuildCycleRoute 등 조립 계층의 이동(2026-09-03, "Beam/GRASP 공용 조립 계층과 어댑터"
    이슈): 노드열 stitching → PathUtils.prune_dead_ends → 거리·재통행비율 재계산 로직은
    GRASP 전용이 아니라 Beam도 같은 기준으로 써야 해서 waypoint_route_builder.py로 옮겼다.
    이 파일은 Route/MissingEdgeAttributeError/BuildCycleRoute를 하위 호환을 위해 그대로
    재-export한다 — 이 모듈 안의 다른 함수(EdgeCost, _CostCache 등 GRASP의 A* 탐색 비용
    정책)는 옮기지 않았다. 그건 "조립"이 아니라 "탐색 비용 정책"이라 GRASP 전용으로 남아야
    한다.

"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional

import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.engines.waypoint_pool import WaypointPoolResult
from src.route_engine.waypoint_route_builder import (
    MissingEdgeAttributeError,
    PathFinder,
    Route,
    _LENGTH_ATTR,
    build_cycle_route as BuildCycleRoute,
    edge_overlap_ratio as _edge_overlap_ratio,
    sum_edge_length as _sum_edge_length,
)

# ── 데이터 구조 ──────────────────────────────────────────────────────────
# Route/MissingEdgeAttributeError/_LENGTH_ATTR은 waypoint_route_builder.py로 옮겼다(위
# docstring 참고). 이 파일에서는 하위 호환을 위해 그대로 재-export해서 쓴다.



@dataclass(frozen=True)
class RouteObjective:
    """사전식 비교 키. feasible(목표거리 허용오차 충족) 여부가 최우선이다.

    feasible=False(허용오차 밖)인 두 해를 비교할 때는 distance_error_m을 먼저 본다 —
    목표 거리에라도 최대한 가까워지는 게 우선이므로.

    feasible=True(허용오차 안)인 두 해를 비교할 때는 repeated_edge_ratio를 distance_error_m
    보다 먼저 본다. 애초에 distance_error_m을 그대로 먼저 비교하면, 실측 그래프에서는
    두 해가 정확히 같은 distance_error_m을 갖는 경우가 거의 없어 repeated_edge_ratio가
    사실상 한 번도 tie-break로 작동하지 않는다(왕복 퇴화 방지가 무력화됨) — 사용자
    피드백("겹치는 경로 말고 O형 경로를 원한다")에 따라, 허용오차 안에서는 "얼마나
    정확히 맞았는지"보다 "얼마나 O자형인지"를 우선하도록 바꿨다."""
    feasible: bool
    distance_error_m: float
    repeated_edge_ratio: float

    def sort_key(self) -> tuple:
        if not self.feasible:
            return (1, self.distance_error_m, self.repeated_edge_ratio)
        return (0, self.repeated_edge_ratio, self.distance_error_m)


_INFEASIBLE = RouteObjective(feasible=False, distance_error_m=float("inf"), repeated_edge_ratio=1.0)


def better(a: RouteObjective, b: RouteObjective) -> bool:
    """a가 b보다 나은 해인지(사전식 비교)."""
    return a.sort_key() < b.sort_key()


class SelectionStatus:
    """벤치마크/로그 전용 상태 표기(요청서 §3.6). 실제 엔진 반환 규격(WalkRouteResponse)은
    바꾸지 않는다 — 각 엔진이 find_path() 실행 후 self.last_selection_status에 이 값 중
    하나를 남겨, benchmark 솔버가 CSV의 selection_status 컬럼으로 그대로 옮겨 적는다."""
    FEASIBLE = "feasible"                        # 목표거리 허용범위와 최소거리 조건 모두 충족
    FALLBACK_DISTANCE = "fallback_distance"       # 최소거리 조건은 만족하지만 목표거리 허용범위 후보가 없음
    NO_VALID_WAYPOINT_PAIR = "no_valid_waypoint_pair"  # 경유지 조합을 하나도 완성하지 못했음


def determine_selection_status(
    best_route: Optional[Route], best_obj: RouteObjective, had_valid_waypoint_pair: bool,
) -> str:
    """GRASP 반복이 모두 끝난 뒤 최종 selection_status를 정한다.

    best_route가 None이면(어떤 반복도 완주된 경로를 만들지 못함) had_valid_waypoint_pair로
    원인을 구분한다 — 한 번도 유효한 경유지 조합(cfg.num_waypoints개 전부)을 못 찾았다면
    NO_VALID_WAYPOINT_PAIR, 조합은 찾았지만(BuildCycleRoute의 A* 연결 실패 등으로) 완주된
    경로가 없었다면 FALLBACK_DISTANCE로 분류한다(요청서가 정의한 3개 상태만 쓰므로, 이
    경우도 가장 가까운 의미인 FALLBACK_DISTANCE에 담는다).

    best_route가 있으면 best_obj.feasible(목표거리 허용범위 충족) 여부로 FEASIBLE/
    FALLBACK_DISTANCE를 가른다 — 최소거리 조건은 이미 후보 생성 단계에서 걸러졌으므로
    best_route가 존재한다는 것 자체가 최소거리 조건을 통과했다는 뜻이다."""
    if best_route is None:
        return SelectionStatus.NO_VALID_WAYPOINT_PAIR if not had_valid_waypoint_pair else SelectionStatus.FALLBACK_DISTANCE
    return SelectionStatus.FEASIBLE if best_obj.feasible else SelectionStatus.FALLBACK_DISTANCE


def is_waypoint_pair_separated(distance_p2_p3_m: float, target_m: float, config: "GraspConfig") -> bool:
    """연속한 두 경유지가 실제 도보 거리 기준으로 서로 충분히 떨어져 있는지 확인한다
    (요청서 §3.3 — 원래는 P2-P3 전용이었으나, 경유지 n개 일반화 이후에는 모든 연속한
    경유지 쌍(waypoints[i], waypoints[i+1])에 동일하게 적용한다). distance_p2_p3_m은
    반드시 실제 A* 경로 거리여야 한다 — Haversine 직선거리로 판정하면 안 된다(요청서
    §3.4). 최소거리 기준은 target_m * config.min_waypoint_separation_ratio.
    (파라미터명은 하위 호환을 위해 유지한다 — 실질 의미는 "연속한 두 경유지 사이 거리".)"""
    minimum = target_m * config.min_waypoint_separation_ratio
    return distance_p2_p3_m >= minimum


def evaluate_route(route: Optional[Route], target_distance_m: float, distance_tolerance_m: float) -> RouteObjective:
    """EvaluateRoute(route, target_distance_m, distance_tolerance_m)."""
    if route is None:
        return _INFEASIBLE
    error = abs(route.distance_m - target_distance_m)
    return RouteObjective(
        feasible=error <= distance_tolerance_m,
        distance_error_m=error,
        repeated_edge_ratio=route.repeated_edge_ratio,
    )


@dataclass(frozen=True)
class GraspConfig:
    grasp_iters: int = 24                # 기존 circular_grasp.py::_GRASP_ITERS와 동일(공정 비교 조건)
    rcl_size: int = 8                    # 기존 circular_grasp.py::_RCL_SIZE와 동일. 구축 RCL 크기이자
                                          # 지역개선 이웃 탐색 폭(BuildCycleRoute 호출 상한)으로도 재사용한다.
    distance_tolerance_ratio: float = 0.05
    # 최종 Route 평가(evaluate_route)의 허용 오차 비율(2026-09-03, "Beam/GRASP 판단 기준
    # 통일" 요청서 3번). 기존에는 target_m과 무관한 절대값(150.0m)이었으나, target_m이
    # 3000이 아닌 호출(예: 5000m)에서 그대로 쓰면 실제 허용 비율이 target_m마다 달라지는
    # 문제가 있어 비율로 바꿨다. 각 호출부는 evaluate_route(route, target_m, target_m *
    # cfg.distance_tolerance_ratio)처럼 매번 target_m으로 다시 곱해 절대 허용치를 구한다.
    # 기본값 0.05(5%)는 기존 150m 기본값을 GRASP·Beam 공통 비교 기준인 target_m=3000m에
    # 대입한 값과 같고, Beam·ALNS 벤치마크가 이미 검증한 tolerance_ratio 값(README
    # "--tolerances 0.025 0.05 0.075" 참고)과도 일치한다.
    pairwise_cache_rows: int = 256       # WaypointPoolGenerator.build_pool(pairwise_cache_rows=...)로 전달
    num_waypoints: int = 2
    # GRASP이 선택하는 경유지 개수(n). 기본값 2는 기존 p2·p3 2개 구성과 완전히 동일한
    # 동작을 보장하는 하위 호환 기본값이다(2026-09-02 "GRASP 경유지 개수를 임의 n으로
    # 확장" 이슈). CircularRouteInput이나 각 엔진 생성자는 아직 이 값을 외부로 노출하지
    # 않는다 — API 연동은 이번 작업 범위 밖이며, 필요하면 GraspConfig(num_waypoints=n)을
    # 직접 만들어 엔진에 전달해야 한다.
    angle_diversity_weight_m: float = 1500.0
    # 다음 경유지 랭킹(_rank_next_waypoint_candidates)에서 "후보가 p1 기준으로 직전
    # 경유지(prev)와 같은 방향이거나 정반대 방향"일 때 더해지는 최대 가상 거리 오차(m).
    # 각도차가 π/2(직각)에 가까울수록 0에 가까워지고, 0(같은 방향) 또는 π(정반대 방향)에
    # 가까울수록 이 값에 가까워진다.
    #
    # 처음에는 "정반대 방향일수록 좋다(선형 보상)"로 구현했으나, 실제 그래프(서울
    # 160,328노드) 재현 결과 p2·p3를 p1 기준 정반대 방향으로 강제하면 p2→p3 최단경로가
    # 대개 p1 근처를 다시 지나게 되어 overlap_ratio가 오히려 1.0(완전 왕복)까지 악화됐다
    # (2026-08-30 확인) — p1이 두 반대 방향 지점 사이의 최단 경로 상에 놓이기 쉽기
    # 때문이다. 같은 방향(0°)과 정반대 방향(180°) 둘 다 "일직선 왕복"을 만드는 조건이고,
    # 직각(90°)에 가까울수록 p1·p2·p3가 삼각형/부채꼴로 펼쳐져 O자형에 가까워진다는 점을
    # 재현으로 확인한 뒤 |cos(각도차)| 형태(0°·180°에서 최댓값, 90°에서 0)로 바꿨다.
    # 값을 키울수록 직각에 가까운 조합을 더 강하게 우선하고, 0으로 두면 이 기능이 완전히
    # 꺼진 이전 동작과 같아진다.
    #
    # 기본값 500.0 → 1500.0 조정 근거(2026-08-30, target_km=5.0·seed=42·start_node=1
    # 실측): rcl_size=8(기존 circular_grasp.py와 맞춘 "공정 비교" 기본값, 아래 rcl_size
    # 주석 참고)을 그대로 둔 채로는, 500.0에서 RCL 안에 진짜 직각에 가까운 후보가 아예
    # 안 들어오는 경우가 있어 Local/VND가 여전히 overlap_ratio=0.714까지 나왔다.
    # 1500.0으로 올리면 같은 rcl_size=8에서 Local/VND overlap_ratio=0.017, VNS
    # overlap_ratio=0.000까지 개선되고 거리 오차도 허용오차(150m) 안에 든다(rcl_size를
    # 16 이상으로 키워도 비슷한 품질에 도달하지만 BuildCycleRoute 호출이 늘어 2배 이상
    # 느려진다 — 계산량을 늘리지 않고 가중치만으로 해결 가능해 이 값을 우선 채택).
    min_waypoint_separation_ratio: float = 0.20
    # 연속한 두 경유지 사이 최소거리 안전장치(요청서 "P2-P3 최소거리와 추가 검증만 반영"
    # §3, 경유지 n개 일반화 이후 모든 연속 쌍에 적용). 방위각 페널티만으로는 "각도는
    # 직각이지만 실제 도보상 두 경유지가 매우 가까운" 그래프 구조에서 여전히 왕복에
    # 가까운 경로가 나올 수 있어, 연속한 두 경유지의 실제 A* 거리(직선거리 아님,
    # WaypointPoolResult.distance)가 target_m * 이 비율 미만인 조합은 애초에
    # _rank_next_waypoint_candidates 랭킹에서 제외한다(is_waypoint_pair_separated).
    # 0으로 두면 이 필터가 완전히 꺼진다. 기존 circular_grasp.py의 두 링(ring1/ring2)
    # 반경 합이 target_m 근처가 되도록 설계된 것과 같은 취지로, "두 경유지가 거의 겹치는
    # 조합"만 걸러내는 최소한의 안전장치 — 전체 구간 균형을 강제하는 것은 아니다
    # (요청서 §4.2에서 명시적으로 금지: 다리·고속도로 등 실제 도보망 단절 때문에 균형을
    # 강한 탈락 기준으로 쓰면 안 됨).


DEFAULT_CONFIG = GraspConfig()


# ── EdgeCost: mode 확장 지점 ─────────────────────────────────────────────

def ConvertNaturalScoreToSearchCost(nature_score, config=None) -> float:
    """TODO(자연 모드, 1차 구현 비활성): nature_score를 탐색 비용으로 변환한다.
    점수 방향(높을수록 좋은지)과 정규화 방식이 아직 데이터 정의서로 확정되지 않았고,
    현재 그래프에는 nature_score 자체가 로드되지 않는다(모듈 docstring 참고).
    """
    raise NotImplementedError(
        "nature_score 변환 정책이 아직 정의되지 않았습니다. 활성화 순서는 이 모듈의 "
        "docstring을 참고하세요."
    )


def CombineDistanceAndNaturalCost(length_m, nature_score, config=None) -> float:
    """TODO(distance_natural 혼합 모드, 1차 구현 비활성)."""
    raise NotImplementedError(
        "distance_natural 결합 정책이 아직 정의되지 않았습니다. 활성화 순서는 이 모듈의 "
        "docstring을 참고하세요."
    )


def EdgeCost(mode: str, edge_data: dict, config=None) -> float:
    """
    엣지 하나의 탐색 비용. GRASP·A*·VND·VNS·최종평가 전체가 동일한 mode를 이 함수
    하나로 전달받아야 한다(한 알고리즘만 다른 비용 기준을 쓰면 비교가 불공정해진다).
    """
    if mode == "distance":
        if _LENGTH_ATTR not in edge_data:
            raise MissingEdgeAttributeError(
                f"엣지에 '{_LENGTH_ATTR}' 속성이 없습니다: {edge_data!r}"
            )
        return edge_data[_LENGTH_ATTR]
    if mode == "natural":
        return ConvertNaturalScoreToSearchCost(edge_data.get("nature_score"), config)
    if mode == "distance_natural":
        return CombineDistanceAndNaturalCost(edge_data.get(_LENGTH_ATTR, 0.0), edge_data.get("nature_score"), config)
    raise ValueError(f"Unknown mode: {mode!r}")


def _sum_edge_cost(G: nx.Graph, path: Optional[list[int]], mode: str, config=None) -> float:
    """현재 mode 기준 탐색 비용 합산(A* 내부 비용 캐시용)."""
    if path is None:
        return float("inf")
    total = 0.0
    for u, v in zip(path, path[1:]):
        total += EdgeCost(mode, G[u][v], config)
    return total


# ── A* 경로 캐시(최종 구간 연결 전용) ────────────────────────────────────

class _CostCache:
    """AStarPath()의 실제 구현 + 캐시. **엔진 인스턴스마다 하나씩** 새로 만든다(모듈
    전역 캐시 아님). 후보 랭킹(어떤 경유지가 좋은가)은 이제 WaypointPoolResult.distance()가
    맡으므로(풀 생성 시점에 cutoff SSSP로 이미 계산됨), 이 캐시는 **BuildCycleRoute가
    최종 구간을 실제로 연결할 때만** 쓰인다 — 실제 노드열이 필요한 지점은 거기뿐이다.
    astar_calls/cache_hits를 누적해 벤치마크 로그에 노출한다.
    """

    def __init__(self, G: nx.Graph, mode: str = "distance", config=None):
        self.G = G
        self.mode = mode
        self.config = config
        self._path_utils = PathUtils(G)
        self._cost_cache: dict[tuple[int, int], float] = {}
        self._path_cache: dict[tuple[int, int], Optional[list[int]]] = {}
        self.astar_calls = 0
        self.cache_hits = 0

    def _weight(self, u, v, edge_data) -> float:
        return EdgeCost(self.mode, edge_data, self.config)

    @staticmethod
    def _key(a: int, b: int) -> tuple[int, int]:
        # 무방향 그래프이므로 대칭 키만 사용한다. 방향 그래프로 바뀌면 이 정렬을 지워야 한다.
        return (a, b) if a <= b else (b, a)

    def astar_path(self, a: int, b: int) -> Optional[list[int]]:
        """AStarPath(a, b, mode) — 실패 시 None(=FAIL). 반환 노드열은 항상 a에서
        시작해 b에서 끝난다. 무방향 그래프라 비용(cost)은 대칭이므로 캐시 키는
        (min,max)로 한 방향만 저장하지만, 반대 방향으로 조회되면 순서를 뒤집어
        돌려준다 — 그렇지 않으면 BuildCycleRoute가 구간을 이어붙일 때 노드열
        순서가 어긋난다."""
        key = self._key(a, b)
        if key in self._path_cache:
            self.cache_hits += 1
            cached = self._path_cache[key]
            if cached is None:
                return None
            return cached if cached[0] == a else list(reversed(cached))

        if a == b:
            path: Optional[list[int]] = [a]
        else:
            self.astar_calls += 1
            try:
                path = self._path_utils.astar_path(a, b, weight=self._weight)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                path = None

        self._path_cache[key] = path
        self._cost_cache[key] = _sum_edge_cost(self.G, path, self.mode, self.config)
        return path

    def astar_path_avoiding_edges(self, a: int, b: int, banned_edges: frozenset) -> Optional[list[int]]:
        """일회성 제약 탐색(VNS Shake level 3 전용): banned_edges에 속한 엣지를 무한대
        비용으로 취급해 우회 경로를 찾는다. **그래프를 복사하지 않는다** — 대형 그래프
        (실측 16만 노드 기준 G.copy() 1회에 약 1.7초)에서 Shake를 반복 호출할 때마다
        복사하면 감당이 안 되므로, weight 콜백만 바꿔 같은 그래프 객체를 그대로 재사용한다.
        결과는 캐시하지 않는다(banned_edges 조합마다 달라지므로 재사용 의미가 없음)."""
        self.astar_calls += 1

        def _weight(u, v, edge_data, _banned=banned_edges):
            if frozenset((u, v)) in _banned:
                return float("inf")
            return EdgeCost(self.mode, edge_data, self.config)

        try:
            return self._path_utils.astar_path(a, b, weight=_weight)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None


# ── 경유지 후보 랭킹(WaypointPoolResult 기반) ────────────────────────────
#
# waypoint_pool.py가 이미 p1 기준 cutoff SSSP(r_max=target_m/2)로 "라운드트립에 포함될
# 수 있는 모든 노드"를 풀 하나로 모아뒀고, 풀 내 임의 두 노드 사이 거리도 lazy+캐시로
# 저렴하게(소스 노드 1개당 SSSP 1회, 그 행 전체를 O(1) 조회로 재사용) 제공한다. 그래서
# 예전처럼 "반경 X±허용오차" 링을 따로 만들 필요 없이, 풀 전체를 대상으로 아래 그리디
# 기준으로 순위만 매기면 된다 — 순위 계산 자체가 이미 저렴하다.

def _bearing_rad(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """(lat1,lon1)에서 (lat2,lon2)로 향하는 초기 방위각(라디안, 정북=0, 시계방향 양수).
    구면 삼각법 공식 — 도심 스케일 거리에서 평면 근사와 오차 차이는 무시할 수준이지만,
    이미 haversine 계열(구면) 공식을 쓰는 코드베이스 관례에 맞춘다."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlon)
    return math.atan2(y, x)


def _angular_separation_rad(bearing_a: float, bearing_b: float) -> float:
    """두 방위각(라디안) 사이의 각도차를 [0, π] 범위로 정규화한다.
    0=같은 방향(왕복 퇴화가 일어나는 조건), π=정반대 방향(가장 O자형에 가까운 조건)."""
    diff = abs(bearing_a - bearing_b) % (2 * math.pi)
    return min(diff, 2 * math.pi - diff)


def _rank_next_waypoint_candidates(
    G: nx.Graph,
    pool_result: WaypointPoolResult,
    p1: int,
    prev: int,
    cumulative_so_far_m: float,
    target_m: float,
    cfg: GraspConfig,
    exclude: frozenset = frozenset(),
) -> list[int]:
    """다음 경유지 후보를 "직전 경유지(prev) 기준" 결합 점수 오름차순으로 정렬한다
    (기존 _rank_p2_candidates/_rank_p3_candidates를 경유지 n개로 일반화한 단일 함수):

        score = |cumulative_so_far_m + dist(prev,c) + dist(p1,c) − target_m|
                + (prev != p1인 경우) cfg.angle_diversity_weight_m · |cos(각도차(p1→prev, p1→c))|

    cumulative_so_far_m은 p1에서 prev까지 이미 확정된 경유지들을 실제로 거쳐온 누적
    거리(m) — 호출부(construct_initial_route 등)가 매 단계 재계산해 넘긴다. dist(p1,c)는
    "c가 이번에 고르는 경유지를 마지막으로 보고 곧장 p1로 돌아간다"고 가정한 근사
    나머지 거리다: 실제로 더 고를 경유지가 남아 있다면 근사치일 뿐이고, 이번이 정말
    마지막(N번째) 경유지라면 이 근사는 실제 나머지 거리와 정확히 같아진다. 매 단계
    p1이 아니라 직전 경유지 기준으로 누적 거리를 다시 계산해야 GRASP의 적응성이
    유지된다 — 각 단계 그리디 점수가 이전 선택과 무관한 독립 샘플링이 되지 않도록 하기
    위함이다.

    prev==p1(첫 경유지를 고르는 단계)이면 cumulative_so_far_m=0이고 dist(prev,c)는
    dist(p1,c)와 같으므로, score의 첫 항은 |2·dist(p1,c) − target_m|로 자동 축약된다 —
    기존 _rank_p2_candidates와 완전히 동일한 동작(candidate 혼자 왕복 턴어라운드
    지점이라 가정한 근사 그리디 기준)이다. 이 단계에서는 비교할 '직전 방향'이 없으므로
    각도 다양성 페널티를 적용하지 않는다(bearing_prev가 정의되지 않음).

    cfg.min_waypoint_separation_ratio > 0이고 prev != p1이면, prev-c 실제 A* 거리
    (WaypointPoolResult.distance — 직선거리 아님)가 target_m * cfg.min_waypoint_separation_ratio
    미만인 후보는 랭킹에서 아예 제외한다(is_waypoint_pair_separated) — 방위각이 직각에
    가까워도 두 지점이 실제 도보상 서로 너무 가까우면 여전히 왕복에 가까운 경로가 나올
    수 있기 때문이다(2026-08-30 P2-P3 최소거리 안전장치 요청서 §3.1 근거, n개로 일반화
    이후에는 모든 연속 쌍에 동일하게 적용). prev==p1이면(첫 경유지 선택) 기존
    _rank_p2_candidates와 동일하게 이 필터를 적용하지 않는다.

    dist(prev,c)는 WaypointPoolResult.distance(prev, c)로 조회하며, prev를 소스로 한
    SSSP 행이 아직 캐시에 없으면 이 호출 안에서 1회만 계산되고, 이후 같은 prev에 대한
    다른 후보 조회는 캐시를 그대로 쓴다 — 후보 하나하나에 실제 경로 탐색을 부르지 않는다."""
    p1_data = G.nodes[p1]

    bearing_prev = None
    if prev != p1 and cfg.angle_diversity_weight_m:
        prev_data = G.nodes[prev]
        bearing_prev = _bearing_rad(p1_data["lat"], p1_data["lon"], prev_data["lat"], prev_data["lon"])

    ranked = []
    for c in pool_result.pool_nodes:
        if c == prev or c in exclude:
            continue

        d_prev_c = pool_result.dist_from_p1[c] if prev == p1 else pool_result.distance(prev, c)
        if d_prev_c is None:
            continue  # r_max 유도 부분그래프 안에서 prev로부터 도달 불가

        if prev != p1 and cfg.min_waypoint_separation_ratio and not is_waypoint_pair_separated(d_prev_c, target_m, cfg):
            continue  # 직전 경유지와 후보가 실제 도보상 너무 가까움 — 왕복 퇴화 위험이 있는 조합이라 제외

        total = cumulative_so_far_m + d_prev_c + pool_result.dist_from_p1[c]
        distance_error = abs(total - target_m)

        if bearing_prev is not None:
            c_data = G.nodes[c]
            bearing_c = _bearing_rad(p1_data["lat"], p1_data["lon"], c_data["lat"], c_data["lon"])
            separation = _angular_separation_rad(bearing_prev, bearing_c)
            diversity_penalty = cfg.angle_diversity_weight_m * abs(math.cos(separation))
        else:
            diversity_penalty = 0.0

        ranked.append((distance_error + diversity_penalty, c))
    ranked.sort(key=lambda pair: pair[0])
    return [c for _, c in ranked]


def _prefix_distances_m(pool_result: WaypointPoolResult, start_node: int, waypoints: list[int]) -> list[float]:
    """waypoints[i]를 고르기 직전까지의 실제 누적 거리(m) 목록(길이 == len(waypoints)) —
    construct_initial_route가 선택 단계마다 계산하는 cumulative_so_far_m과 동일한 정의를,
    이미 확정된 경유지 순서로부터 사후에 재계산한다. 지역탐색 이웃 함수들이 특정 위치의
    경유지만 바꿔치기할 때, 그 위치의 '직전까지 누적 거리'를 다시 구하기 위해 쓴다."""
    cum = [0.0]
    prev = start_node
    for w in waypoints[:-1]:
        step = pool_result.dist_from_p1[w] if prev == start_node else pool_result.distance(prev, w)
        cum.append(cum[-1] + step)
        prev = w
    return cum


# ── 순환 경로 구축 ───────────────────────────────────────────────────────

def format_optional(value: Optional[float], digits: int = 0) -> str:
    """로그 문자열용 헬퍼 — None이면 'n/a', 아니면 소수점 digits자리로 반올림한 문자열.
    (아래 RouteGeometryMetrics 필드처럼 route가 없으면 None일 수 있는 스칼라 값들을 %s로
    로깅할 때 4개 엔진이 공통으로 쓴다.)"""
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def format_optional_list(values: Optional[list[float]], digits: int = 0) -> str:
    """format_optional의 리스트 버전 — None이면 'n/a', 아니면 각 원소를 반올림해 나열한다
    (RouteGeometryMetrics.segment_lengths_m/waypoint_angle_diffs_deg처럼 경유지 개수 n에
    따라 길이가 달라지는 필드를 로깅할 때 쓴다)."""
    if values is None:
        return "n/a"
    return "[" + ", ".join(f"{v:.{digits}f}" for v in values) + "]"


# ── 원형성 진단 지표(요청서: "최종 경로가 실제로 원형에 가까운지", 2026-08-30) ───
#
# 아래 지표는 최종 채택된 Route 하나에 대해서만 계산한다(GRASP 탐색 중 매 후보마다
# 계산하지 않음 — 탐색 자체의 accept/reject 기준을 바꾸지 않는다는 이번 요청의 명시적
# 제약과, 이미 존재하는 angle_diversity_weight_m/min_waypoint_separation_ratio 기반
# 탐색 로직을 건드리지 않는다는 원칙을 그대로 지킨다). 구간 거리는 이미 채워진
# _CostCache를 재사용하므로 추가 A* 호출이 생기지 않는다.

@dataclass(frozen=True)
class RouteGeometryMetrics:
    """경유지 n개 일반화 이후 리스트 기반으로 재설계한 원형성 진단 지표. Route가
    없으면(폴백 등) 전부 None/False로 채운다 — CSV/로그 어느 쪽에서도 그대로 옮겨 적을
    수 있는 형태.

    segment_lengths_m: [p1→w1, w1→w2, ..., w_N→p1] 구간 거리(m), 길이 N+1.
        N=2(기존 기본 구성)에서는 [d12, d23, d31]과 완전히 같다.
    waypoint_separation_m: 내부 구간(segment_lengths_m[1:-1], 즉 첫/마지막 왕복 구간을
        제외한 "경유지-경유지" 구간들) 중 최솟값 — 연속한 두 경유지가 서로 얼마나
        가까워질 수 있는지의 대리 지표. N=2에서는 내부 구간이 d23 하나뿐이라 기존
        waypoint_separation_m(P2-P3 거리)과 동일한 값이 된다. 경유지가 1개뿐이면(내부
        구간 자체가 없음) None.
    waypoint_angle_diffs_deg: 연속한 두 경유지의 p1 기준 방위각차(0~180도) 목록, 길이
        N-1. N=2에서는 원소 1개짜리 리스트가 되어 기존 waypoint_angle_diff_deg(스칼라)와
        같은 값을 담는다. 경유지가 1개뿐이면 빈 리스트.
    segment_balance_ratio: min(segment_lengths_m) / max(segment_lengths_m), 0~1.
    """
    segment_lengths_m: Optional[list[float]]
    repeated_edge_ratio: Optional[float]
    waypoint_separation_m: Optional[float]
    waypoint_angle_diffs_deg: Optional[list[float]]
    segment_balance_ratio: Optional[float]
    is_degenerate_loop: bool


_DEGENERATE_REPEATED_EDGE_RATIO = 0.35
# repeated_edge_ratio 판정 임계값(2026-09-02, "Beam·GRASP 재통행·거리허용 판단 기준 통일" 요청서).
#
# 기존 0.50은 _edge_overlap_ratio가 "재통행 횟수" 기준(구간이 2회 이상 통행되면 그 통행
# 전부를 reused로 셈 — 단순 왕복이면 1.0)이던 시절 값이다. 이번에 _edge_overlap_ratio를
# Beam·ALNS와 같은 거리 가중 정의(waypoint_evaluation.py::RouteEvaluator — 구간의 "두
# 번째 이후 통행분"만 repeated에 더함)로 바꾸면서, 같은 "단순 왕복"의 값이 1.0에서 0.5로
# 내려간다(RouteEvaluator 모듈 문서 "단순 왕복은 50%, 재통행 없는 순환은 0%" 참고).
# 기존 0.50 임계값을 그대로 두면 가장 흔한 퇴화 형태인 단순 왕복이 정확히 경계값에 걸려
# `repeated_edge_ratio > 0.50` 비교를 통과하지 못한다(퇴화로 잡히지 않는다) — 판정이
# 사실상 무력화된다. 0.5보다 확실히 낮은 값이 필요해 0.35로 재조정했다: 단순 왕복(0.5)은
# 여유를 두고 확실히 잡아내면서, 짧은 막다른 구간을 잠깐 오간 정도(낮은
# repeated_edge_ratio)까지 과도하게 퇴화로 잡지는 않도록 하는 절충값이다.
#
# 이 값은 지표 정의 전환을 반영한 1차 재조정값이며, 요청서 ETC가 요구하는 실제 그래프
# 변경 전/후 벤치마크 회귀 확인은 아직 하지 않았다 — 실측 후 이 상수와 주석을 함께 갱신할 것.


def is_degenerate_loop_route(
    repeated_edge_ratio: float,
    waypoint_separation_m: Optional[float],
    target_m: float,
    segment_balance_ratio: Optional[float],
) -> bool:
    """요청서 원문 그대로의 OR 조건(순수 함수로 분리 — compute_route_geometry_metrics와
    별개로 단위 테스트하기 위함). 값이 없는(None) 조건은 그 항목만 건너뛴다(예: 경유지가
    1개뿐이라 waypoint_separation_m을 못 구했다면 그 조건 없이 나머지 두 개로만 판정).
        repeated_edge_ratio > _DEGENERATE_REPEATED_EDGE_RATIO(0.35, 재조정 근거는 위 상수 주석 참고)
        또는 waypoint_separation_m(내부 구간 최솟값) < target_m * 0.20
        또는 segment_balance_ratio < 0.25
    """
    if repeated_edge_ratio > _DEGENERATE_REPEATED_EDGE_RATIO:
        return True
    if waypoint_separation_m is not None and target_m > 0 and waypoint_separation_m < target_m * 0.20:
        return True
    if segment_balance_ratio is not None and segment_balance_ratio < 0.25:
        return True
    return False



def compute_route_geometry_metrics(
    G: nx.Graph, path_finder: PathFinder, start_node: int, route: Optional[Route], target_m: float,
) -> RouteGeometryMetrics:
    """route가 None이면 전부 None/False. 아니면 p1→w1→...→w_N→p1의 각 구간을
    path_finder()로 다시 조회해(이미 BuildCycleRoute가 계산해둔 경로라 호출자가 같은
    캐시를 넘겼다면 캐시 적중, 새 A* 호출 없음) 실제 거리로 segment_lengths_m을 구하고,
    나머지 지표를 그 위에서 계산한다. path_finder는 GRASP 전용 _CostCache.astar_path
    (bound method)뿐 아니라 waypoint_route_builder.py::DistancePathFinder.astar_path
    등 PathFinder 계약(waypoint_route_builder.py::PathFinder)을 만족하는 어떤 콜러블도
    받을 수 있다 — GRASP·Beam이 같은 함수로 CSV 지표를 채우기 위한 일반화(refactor/394).

    is_degenerate_loop 판정 기준(요청서 원문 그대로, 하드코딩된 리터럴
    — GraspConfig.min_waypoint_separation_ratio 등 탐색용 설정과는 독립적인 별도 진단
    임계값이다. repeated_edge_ratio 임계값 재조정 근거는 _DEGENERATE_REPEATED_EDGE_RATIO
    상수 주석 참고):
        repeated_edge_ratio > _DEGENERATE_REPEATED_EDGE_RATIO(0.35)
        또는 waypoint_separation_m(내부 구간 최솟값) < target_m * 0.20
        또는 segment_balance_ratio < 0.25
    세 구간 균형(segment_balance_ratio)은 이번 단계에서 탐색을 막는 강한 조건이 아니라
    이 진단 플래그에서만 쓰인다 — 요청서가 명시적으로 요구한 제약이다."""
    if route is None:
        return RouteGeometryMetrics(None, None, None, None, None, False)

    stops = [start_node, *route.waypoints, start_node]
    segment_lengths_m: list[float] = []
    for a, b in zip(stops, stops[1:]):
        path = path_finder(a, b)
        if path is None:
            # BuildCycleRoute가 이미 성공한 route라면 이론상 도달하지 않는 경로지만,
            # 캐시가 비어 있는 상태로 이 함수만 단독 호출된 경우까지 안전하게 처리한다.
            return RouteGeometryMetrics(None, route.repeated_edge_ratio, None, None, None, False)
        segment_lengths_m.append(_sum_edge_length(G, path))

    have_coords = all(
        "lat" in G.nodes[n] and "lon" in G.nodes[n] for n in (start_node, *route.waypoints)
    )
    angle_diffs_deg: Optional[list[float]] = None
    if have_coords:
        p1_data = G.nodes[start_node]
        bearings = [
            _bearing_rad(p1_data["lat"], p1_data["lon"], G.nodes[w]["lat"], G.nodes[w]["lon"])
            for w in route.waypoints
        ]
        angle_diffs_deg = [
            math.degrees(_angular_separation_rad(bearings[i], bearings[i + 1]))
            for i in range(len(bearings) - 1)
        ]

    interior_segments = segment_lengths_m[1:-1]  # 첫/마지막(p1과 맞닿은 왕복 구간) 제외한 내부 구간들
    waypoint_separation_m = min(interior_segments) if interior_segments else None

    largest = max(segment_lengths_m)
    balance_ratio = (min(segment_lengths_m) / largest) if largest > 0 else None

    degenerate = is_degenerate_loop_route(route.repeated_edge_ratio, waypoint_separation_m, target_m, balance_ratio)

    return RouteGeometryMetrics(
        segment_lengths_m=segment_lengths_m,
        repeated_edge_ratio=route.repeated_edge_ratio,
        waypoint_separation_m=waypoint_separation_m,
        waypoint_angle_diffs_deg=angle_diffs_deg,
        segment_balance_ratio=balance_ratio,
        is_degenerate_loop=degenerate,
    )


@dataclass(frozen=True)
class ConstructionResult:
    """construct_initial_route()의 반환값. route는 완주된 경로(실패 시 None). p1은
    pool_result.pool_nodes에 애초에 포함되지 않으므로(waypoint_pool.py), 어떤 경유지가
    start_node와 같아지는 퇴화 사례는 후보 목록 단계에서 이미 불가능하다.

    had_valid_waypoint_pair는 cfg.num_waypoints개의 경유지 선택을 이번 호출에서 전부
    완성했는지(=매 단계 rcl이 비지 않았는지)를 표시한다(필드명은 하위 호환을 위해
    유지) — route가 None이더라도(예: BuildCycleRoute의 A* 연결 실패) 경유지 조합 자체는
    완성했을 수 있으므로 route 유무와는 독립적인 신호다. 엔진의 find_path()가 GRASP
    반복 전체에서 이 값을 OR로 누적해, 최종 selection_status가 NO_VALID_WAYPOINT_PAIR인지
    FALLBACK_DISTANCE인지 구분하는 데 쓴다(determine_selection_status 참고)."""
    route: Optional[Route]
    had_valid_waypoint_pair: bool


def construct_initial_route(
    G: nx.Graph,
    cost_cache: _CostCache,
    pool_result: WaypointPoolResult,
    start_node: int,
    target_m: float,
    rng: random.Random,
    cfg: GraspConfig,
) -> ConstructionResult:
    """GRASP 구축 단계 — 4개 엔진(local/VND/VNS/ALNS)이 동일하게 사용한다. cfg.num_waypoints개의
    경유지를 직전 경유지 기준 적응적 랭킹으로 하나씩 순서대로 뽑는다 — 각 단계 그리디
    점수는 항상 이전 단계까지의 실제 누적 거리를 반영해 다시 계산되므로, 경유지가
    늘어나도 서로 독립적인 샘플링이 되지 않는다(GRASP의 적응성 유지)."""
    waypoints: list[int] = []
    prev = start_node
    cumulative_m = 0.0

    for _ in range(cfg.num_waypoints):
        rcl = _rank_next_waypoint_candidates(
            G, pool_result, start_node, prev, cumulative_m, target_m, cfg,
            exclude=frozenset(waypoints),
        )[: cfg.rcl_size]
        if not rcl:
            return ConstructionResult(route=None, had_valid_waypoint_pair=False)
        chosen = rng.choice(rcl)

        step_d = pool_result.dist_from_p1[chosen] if prev == start_node else pool_result.distance(prev, chosen)
        cumulative_m += step_d
        waypoints.append(chosen)
        prev = chosen

    route = BuildCycleRoute(G, cost_cache.astar_path, start_node, waypoints)
    return ConstructionResult(route=route, had_valid_waypoint_pair=True)


# ── 지역개선 이웃 ────────────────────────────────────────────────────────

def waypoint_replacement_neighbors(
    G: nx.Graph,
    cost_cache: _CostCache,
    pool_result: WaypointPoolResult,
    start_node: int,
    route: Route,
    target_m: float,
    cfg: GraspConfig,
):
    """WaypointReplacement 이웃: 경유지를 한 번에 하나씩(위치별로) 다른 풀 후보로
    교체한다. 각 위치는 그 직전 경유지(prev)와 거기까지의 실제 누적 거리를 기준으로
    GRASP 구축 단계와 동일한 적응적 랭킹(_rank_next_waypoint_candidates)을 재사용해
    후보를 다시 매긴다. 각 위치 모두 상위 rcl_size개 후보로 탐색 폭을 제한한다(랭킹
    자체는 저렴하지만, 각 후보마다 BuildCycleRoute의 실제 A* N+1회는 비용이 있으므로
    그 호출 횟수를 제한). N=2(경유지 2개)에서는 위치가 정확히 2개(waypoint2, waypoint3
    자리)라 기존 동작과 완전히 같다."""
    waypoints = route.waypoints
    cum = _prefix_distances_m(pool_result, start_node, waypoints)
    fixed_exclude_all = frozenset(waypoints)

    for i in range(len(waypoints)):
        prev = start_node if i == 0 else waypoints[i - 1]
        for c in _rank_next_waypoint_candidates(
            G, pool_result, start_node, prev, cum[i], target_m, cfg,
            exclude=fixed_exclude_all,
        )[: cfg.rcl_size]:
            new_waypoints = list(waypoints)
            new_waypoints[i] = c
            candidate = BuildCycleRoute(G, cost_cache.astar_path, start_node, new_waypoints)
            if candidate is not None:
                yield candidate


def waypoint_pair_replacement_neighbors(
    G: nx.Graph,
    cost_cache: _CostCache,
    pool_result: WaypointPoolResult,
    start_node: int,
    route: Route,
    target_m: float,
    cfg: GraspConfig,
):
    """WaypointPairReplacement 이웃: 인접한 경유지 두 자리(위치 i, i+1)를 함께 바꾼다.
    N=2(경유지 2개)일 때는 유일한 인접 쌍이 곧 waypoint2·waypoint3라 기존 동작과 완전히
    같다. N>2로 확장되면 가능한 모든 인접 쌍(위치)을 순회한다 — 전체 조합(경유지 전부를
    동시에 바꾸는 O(rcl^N))은 비용이 감당 안 되므로 인접 두 자리로만 제한하고, 각 쌍
    탐색은 기존과 동일하게 양쪽 rcl_size로 제한한 O(rcl×rcl)로 유지한다."""
    waypoints = route.waypoints
    cum = _prefix_distances_m(pool_result, start_node, waypoints)

    for i in range(len(waypoints) - 1):
        prev = start_node if i == 0 else waypoints[i - 1]
        fixed_exclude = frozenset(waypoints) - {waypoints[i], waypoints[i + 1]}

        for a in _rank_next_waypoint_candidates(
            G, pool_result, start_node, prev, cum[i], target_m, cfg, exclude=fixed_exclude,
        )[: cfg.rcl_size]:
            step_a = pool_result.dist_from_p1[a] if prev == start_node else pool_result.distance(prev, a)
            cum_a = cum[i] + step_a

            for b in _rank_next_waypoint_candidates(
                G, pool_result, start_node, a, cum_a, target_m, cfg,
                exclude=fixed_exclude | {a},
            )[: cfg.rcl_size]:
                if a == waypoints[i] and b == waypoints[i + 1]:
                    continue
                new_waypoints = list(waypoints)
                new_waypoints[i], new_waypoints[i + 1] = a, b
                candidate = BuildCycleRoute(G, cost_cache.astar_path, start_node, new_waypoints)
                if candidate is not None:
                    yield candidate


def alternative_segment_neighbors(*args, **kwargs):
    """VND 이웃 3(AlternativeSegment): 같은 경유지 조합을 유지하면서 한 구간의 대체 A*
    경로를 탐색. **1차 구현에서는 비활성화**됨 — A*가 동일한 두 노드 사이에 항상 하나의
    경로만 반환하는 현재 구조를 확장해야 하므로(요청서 §8), circular_grasp_waypoint_vnd.py의
    이웃 목록에 등록하지 않는다."""
    raise NotImplementedError("AlternativeSegment는 1차 구현에서 비활성화되어 있습니다.")
