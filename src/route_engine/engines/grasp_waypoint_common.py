"""
src/route_engine/engines/grasp_waypoint_common.py

경유지(waypoint) 선택 기반 GRASP 계열 엔진(local/VND/VNS, circular_grasp_waypoint_*.py)이
공유하는 순수 로직. GRASP은 여기서 전체 경로를 직접 만들지 않고 경유지 2개(p2, p3)만
선택하며, 실제 구간 연결(p1→p2→p3→p1)은 NetworkX A*(PathUtils.astar_path 경유)가 담당한다.

경유지 후보는 waypoint_pool.py::WaypointPoolGenerator/WaypointPoolResult를 그대로 쓴다
(p1 기준 cutoff SSSP 단일 풀 + lazy 거리 캐시, r_max=target_m/2 — 논문 근거는
waypoint_pool.py 모듈 docstring 참고). 이전에 이 파일에 직접 구현했던 Haversine 사전필터
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
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional

import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.engines.waypoint_pool import WaypointPoolResult

_LENGTH_ATTR = "length"  # 그래프 엣지 거리 속성명(위 docstring 참고). 이 상수 하나로 통일.


class MissingEdgeAttributeError(KeyError):
    """엣지에 필수 속성(예: length)이 없을 때 던진다. 0으로 조용히 대체하지 않는다 —
    그렇게 하면 모든 비용이 0으로 계산되는 오류가 숨겨질 수 있다."""


# ── 데이터 구조 ──────────────────────────────────────────────────────────

@dataclass
class Route:
    node_ids: list[int]
    waypoint2: int
    waypoint3: int
    distance_m: float
    repeated_edge_ratio: float


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
    NO_VALID_WAYPOINT_PAIR = "no_valid_waypoint_pair"  # P2-P3 최소거리 조건을 만족하는 조합이 하나도 없었음


def determine_selection_status(
    best_route: Optional[Route], best_obj: RouteObjective, had_valid_waypoint_pair: bool,
) -> str:
    """GRASP 반복이 모두 끝난 뒤 최종 selection_status를 정한다.

    best_route가 None이면(어떤 반복도 완주된 경로를 만들지 못함) had_valid_waypoint_pair로
    원인을 구분한다 — 한 번도 최소거리 조건을 만족하는 (p2,p3) 조합을 못 찾았다면
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
    """P2-P3가 실제 도보 거리 기준으로 서로 충분히 떨어져 있는지 확인한다(요청서 §3.3).
    distance_p2_p3_m은 반드시 실제 A* 경로 거리여야 한다 — Haversine 직선거리로 판정하면
    안 된다(요청서 §3.4). 최소거리 기준은 target_m * config.min_waypoint_separation_ratio."""
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
    distance_tolerance_m: float = 150.0  # 최종 Route 평가(evaluate_route)의 허용 오차
    pairwise_cache_rows: int = 256       # WaypointPoolGenerator.build_pool(pairwise_cache_rows=...)로 전달
    angle_diversity_weight_m: float = 1500.0
    # p3 랭킹(_rank_p3_candidates)에서 "p3가 p1 기준으로 p2와 같은 방향이거나 정반대
    # 방향"일 때 더해지는 최대 가상 거리 오차(m). 각도차가 π/2(직각)에 가까울수록 0에
    # 가까워지고, 0(같은 방향) 또는 π(정반대 방향)에 가까울수록 이 값에 가까워진다.
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
    # P2-P3 최소거리 안전장치(요청서 "P2-P3 최소거리와 추가 검증만 반영" §3). 방위각
    # 페널티만으로는 "각도는 직각이지만 실제 도보상 P2·P3가 매우 가까운" 그래프 구조에서
    # 여전히 왕복에 가까운 경로가 나올 수 있어, P2-P3 실제 A* 거리(직선거리 아님,
    # WaypointPoolResult.distance)가 target_m * 이 비율 미만인 조합은 애초에
    # _rank_p3_candidates 랭킹에서 제외한다(is_waypoint_pair_separated). 0으로 두면
    # 이 필터가 완전히 꺼진다. 기존 circular_grasp.py의 두 링(ring1/ring2) 반경 합이
    # target_m 근처가 되도록 설계된 것과 같은 취지로, "두 경유지가 거의 겹치는 조합"만
    # 걸러내는 최소한의 안전장치 — 세 구간(d12/d23/d31) 균형을 강제하는 것은 아니다
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


def _sum_edge_length(G: nx.Graph, path: list[int]) -> float:
    """항상 실제 물리적 거리(length)만 합산한다 — mode와 무관. Route.distance_m /
    목표거리 비교는 항상 이 값을 쓴다(탐색 비용이 mode에 따라 달라지더라도)."""
    total = 0.0
    for u, v in zip(path, path[1:]):
        edge = G[u][v]
        if _LENGTH_ATTR not in edge:
            raise MissingEdgeAttributeError(f"엣지에 '{_LENGTH_ATTR}' 속성이 없습니다: {edge!r}")
        total += edge[_LENGTH_ATTR]
    return total


def _sum_edge_cost(G: nx.Graph, path: Optional[list[int]], mode: str, config=None) -> float:
    """현재 mode 기준 탐색 비용 합산(A* 내부 비용 캐시용)."""
    if path is None:
        return float("inf")
    total = 0.0
    for u, v in zip(path, path[1:]):
        total += EdgeCost(mode, G[u][v], config)
    return total


def _edge_overlap_ratio(path: list[int]) -> float:
    """경로가 자기 자신의 구간을 재사용하는 비율(benchmark.py::_compute_edge_overlap_ratio와
    동일한 정의 — 무방향 그래프이므로 (u,v)/(v,u)는 같은 구간으로 취급)."""
    if len(path) < 2:
        return 0.0
    counts: dict[frozenset, int] = {}
    for u, v in zip(path, path[1:]):
        key = frozenset((u, v))
        counts[key] = counts.get(key, 0) + 1
    total = sum(counts.values())
    if total == 0:
        return 0.0
    reused = sum(c for c in counts.values() if c > 1)
    return reused / total


# ── A* 경로 캐시(최종 구간 연결 전용) ────────────────────────────────────

class _CostCache:
    """AStarPath()의 실제 구현 + 캐시. **엔진 인스턴스마다 하나씩** 새로 만든다(모듈
    전역 캐시 아님). 후보 랭킹(어떤 p2/p3가 좋은가)은 이제 WaypointPoolResult.distance()가
    맡으므로(풀 생성 시점에 cutoff SSSP로 이미 계산됨), 이 캐시는 **BuildCycleRoute가
    최종 3구간을 실제로 연결할 때만** 쓰인다 — 실제 노드열이 필요한 지점은 거기뿐이다.
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
# 예전처럼 "반경 X±허용오차" 링을 따로 만들 필요 없이, 풀 전체를 대상으로 아래 두
# 그리디 기준으로 순위만 매기면 된다 — 순위 계산 자체가 이미 저렴하다.

def _rank_p2_candidates(pool_result: WaypointPoolResult, target_m: float, exclude: frozenset = frozenset()) -> list[int]:
    """p2 후보를 |2·dist(p1,c) − target_m| 오름차순으로 정렬한다 — p2 혼자 왕복
    턴어라운드 지점이라고 가정했을 때 목표 거리에 가장 가까운 후보가 먼저 오도록 하는
    근사 그리디 기준이다(실제로는 p3가 더해지므로 근사치일 뿐이며, 최종 판단은 항상
    BuildCycleRoute의 실제 A* 거리로 한다)."""
    candidates = [c for c in pool_result.pool_nodes if c not in exclude]
    candidates.sort(key=lambda c: abs(2 * pool_result.dist_from_p1[c] - target_m))
    return candidates


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


def _rank_p3_candidates(
    G: nx.Graph,
    pool_result: WaypointPoolResult,
    p1: int,
    p2: int,
    target_m: float,
    cfg: GraspConfig,
    exclude: frozenset = frozenset(),
) -> list[int]:
    """p2가 이미 정해진 상태에서 p3 후보를 다음 결합 점수 오름차순으로 정렬한다:

        score = |dist(p1,p2)+dist(p2,c)+dist(p1,c) − target_m|
                + cfg.angle_diversity_weight_m · |cos(각도차(p1→p2, p1→c))|

    첫 항은 기존과 동일한 목표거리 적합도. 둘째 항은 방향 다양성 페널티로, c가 p1
    기준으로 p2와 같은 방향(각도차→0)이거나 정반대 방향(각도차→π)일 때 최대가 되고,
    직각(각도차=π/2)에 가까울수록 0이 된다 — 같은 방향은 그대로 왕복 퇴화이고, 정반대
    방향도 p2→p3 최단경로가 대개 p1 부근을 다시 지나며 사실상 왕복이 되므로(GraspConfig.
    angle_diversity_weight_m 주석의 실측 근거 참고) 둘 다 피해야 한다. p1·p2·p3가
    삼각형처럼 펼쳐지는 직각 근방 조합을 우선해 O자형에 가까운 경유지 조합을 고른다.
    cfg.angle_diversity_weight_m=0이면 이 페널티가 완전히 꺼진다.

    점수를 매기기 전에, cfg.min_waypoint_separation_ratio > 0이면 P2-P3 실제 A* 거리
    (WaypointPoolResult.distance — 직선거리 아님)가 target_m * cfg.min_waypoint_separation_ratio
    미만인 후보는 랭킹에서 아예 제외한다(is_waypoint_pair_separated) — 방위각이 직각에
    가까워도 두 지점이 실제 도보상 서로 너무 가까우면 여전히 왕복에 가까운 경로가 나올
    수 있기 때문이다(2026-08-30 P2-P3 최소거리 안전장치 요청서 §3.1 근거). cfg.
    min_waypoint_separation_ratio=0이면 이 필터도 완전히 꺼진다.

    dist(p2,c)는 WaypointPoolResult.distance(p2, c)로 조회하며, p2를 소스로 한 SSSP
    행이 아직 캐시에 없으면 이 호출 안에서 1회만 계산되고, 이후 같은 p2에 대한 다른
    후보 조회는 캐시를 그대로 쓴다 — 후보 하나하나에 실제 경로 탐색을 부르지 않는다."""
    base = pool_result.dist_from_p1[p2]

    p1_data = G.nodes[p1]
    p2_data = G.nodes[p2]
    bearing_p2 = _bearing_rad(p1_data["lat"], p1_data["lon"], p2_data["lat"], p2_data["lon"])

    ranked = []
    for c in pool_result.pool_nodes:
        if c == p2 or c in exclude:
            continue
        d = pool_result.distance(p2, c)
        if d is None:
            continue  # r_max 유도 부분그래프 안에서 p2로부터 도달 불가
        if cfg.min_waypoint_separation_ratio and not is_waypoint_pair_separated(d, target_m, cfg):
            continue  # P2-P3가 실제 도보상 너무 가까움 — 왕복 퇴화 위험이 있는 조합이라 제외

        total = base + d + pool_result.dist_from_p1[c]
        distance_error = abs(total - target_m)

        if cfg.angle_diversity_weight_m:
            c_data = G.nodes[c]
            bearing_c = _bearing_rad(p1_data["lat"], p1_data["lon"], c_data["lat"], c_data["lon"])
            separation = _angular_separation_rad(bearing_p2, bearing_c)
            diversity_penalty = cfg.angle_diversity_weight_m * abs(math.cos(separation))
        else:
            diversity_penalty = 0.0

        ranked.append((distance_error + diversity_penalty, c))
    ranked.sort(key=lambda pair: pair[0])
    return [c for _, c in ranked]


# ── 순환 경로 구축 ───────────────────────────────────────────────────────

def BuildCycleRoute(
    G: nx.Graph,
    cost_cache: _CostCache,
    start_node: int,
    waypoint2: int,
    waypoint3: int,
) -> Optional[Route]:
    """p1→p2→p3→p1 세 구간을 실제 A*로 연결한다. 하나라도 실패하면 None(FAIL).
    distance_m은 반드시 반환된 실제 노드열의 엣지 길이 합산이며, 세 구간의 추정
    비용을 단순히 더한 값이 아니다.

    왕복 가지 제거(PathUtils.prune_dead_ends)를 여기서 미리 적용한다 — 그렇지 않으면
    "잠깐 나갔다가 그대로 되돌아오는" 구간이 raw 거리 합산에는 그대로 두 번 반영되어
    목표거리에 가까운 것처럼 보이지만, 실제로는 최종 표시 단계에서 똑같이 pruning되어
    거리가 크게 줄어드는 경로를 GRASP가 잘못 선택하게 된다. distance_m/repeated_edge_ratio를
    pruning 이후 기준으로 통일해 이 불일치를 없앤다.
    """
    path12 = cost_cache.astar_path(start_node, waypoint2)
    if path12 is None:
        return None
    path23 = cost_cache.astar_path(waypoint2, waypoint3)
    if path23 is None:
        return None
    path31 = cost_cache.astar_path(waypoint3, start_node)
    if path31 is None:
        return None

    node_ids = path12 + path23[1:] + path31[1:]  # 구간 경계 중복 노드는 한 번만 남긴다
    if len(node_ids) < 2:
        return None

    pruned = PathUtils(G).prune_dead_ends(node_ids)
    if len(pruned) < 2:
        return None

    distance_m = _sum_edge_length(G, pruned)
    repeated_edge_ratio = _edge_overlap_ratio(pruned)
    return Route(
        node_ids=pruned,
        waypoint2=waypoint2,
        waypoint3=waypoint3,
        distance_m=distance_m,
        repeated_edge_ratio=repeated_edge_ratio,
    )


def format_optional(value: Optional[float], digits: int = 0) -> str:
    """로그 문자열용 헬퍼 — None이면 'n/a', 아니면 소수점 digits자리로 반올림한 문자열.
    (아래 RouteGeometryMetrics 필드처럼 route가 없으면 None일 수 있는 값들을 %s로
    로깅할 때 4개 엔진이 공통으로 쓴다.)"""
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


# ── 원형성 진단 지표(요청서: "최종 경로가 실제로 원형에 가까운지", 2026-08-30) ───
#
# 아래 지표는 최종 채택된 Route 하나에 대해서만 계산한다(GRASP 탐색 중 매 후보마다
# 계산하지 않음 — 탐색 자체의 accept/reject 기준을 바꾸지 않는다는 이번 요청의 명시적
# 제약과, 이미 존재하는 angle_diversity_weight_m/min_waypoint_separation_ratio 기반
# 탐색 로직을 건드리지 않는다는 원칙을 그대로 지킨다). d12/d23/d31은 이미 채워진
# _CostCache를 재사용하므로 추가 A* 호출이 생기지 않는다.

@dataclass(frozen=True)
class RouteGeometryMetrics:
    """요청서가 지정한 7개 지표 + is_degenerate_loop 판정. Route가 없으면(폴백 등)
    전부 None/False로 채운다 — CSV/로그 어느 쪽에서도 그대로 옮겨 적을 수 있는 형태."""
    segment_p1_p2_m: Optional[float]
    segment_p2_p3_m: Optional[float]
    segment_p3_p1_m: Optional[float]
    repeated_edge_ratio: Optional[float]
    waypoint_separation_m: Optional[float]     # = segment_p2_p3_m(P2-P3 실제 A* 거리)와 동일값,
                                                # 요청서가 지정한 이름으로 별도 노출
    waypoint_angle_diff_deg: Optional[float]   # P1 기준 방위각(P1→P2, P1→P3) 차이, 0~180도
    segment_balance_ratio: Optional[float]     # min(d12,d23,d31) / max(d12,d23,d31), 0~1
    is_degenerate_loop: bool


def is_degenerate_loop_route(
    repeated_edge_ratio: float,
    waypoint_separation_m: Optional[float],
    target_m: float,
    segment_balance_ratio: Optional[float],
) -> bool:
    """요청서 원문 그대로의 OR 조건(순수 함수로 분리 — compute_route_geometry_metrics와
    별개로 단위 테스트하기 위함). 값이 없는(None) 조건은 그 항목만 건너뛴다(예: 좌표가
    없어 segment_balance_ratio를 못 구했다면 그 조건 없이 나머지 두 개로만 판정).
        repeated_edge_ratio > 0.50
        또는 waypoint_separation_m(P2-P3) < target_m * 0.20
        또는 segment_balance_ratio < 0.25
    """
    if repeated_edge_ratio > 0.50:
        return True
    if waypoint_separation_m is not None and target_m > 0 and waypoint_separation_m < target_m * 0.20:
        return True
    if segment_balance_ratio is not None and segment_balance_ratio < 0.25:
        return True
    return False


def compute_route_geometry_metrics(
    G: nx.Graph, cost_cache: _CostCache, start_node: int, route: Optional[Route], target_m: float,
) -> RouteGeometryMetrics:
    """route가 None이면 전부 None/False. 아니면 P1-P2, P2-P3, P3-P1 세 구간을
    cost_cache.astar_path()로 다시 조회해(이미 BuildCycleRoute가 계산해둔 경로라 캐시
    적중, 새 A* 호출 없음) 실제 거리로 d12/d23/d31을 구하고, 나머지 지표를 그 위에서
    계산한다. is_degenerate_loop 판정 기준(요청서 원문 그대로, 하드코딩된 리터럴 —
    GraspConfig.min_waypoint_separation_ratio 등 탐색용 설정과는 독립적인 별도 진단
    임계값이다):
        repeated_edge_ratio > 0.50
        또는 waypoint_separation_m(P2-P3) < target_m * 0.20
        또는 segment_balance_ratio < 0.25
    세 구간 균형(segment_balance_ratio)은 이번 단계에서 탐색을 막는 강한 조건이 아니라
    이 진단 플래그에서만 쓰인다 — 요청서가 명시적으로 요구한 제약이다."""
    if route is None:
        return RouteGeometryMetrics(None, None, None, None, None, None, None, False)

    p1, p2, p3 = start_node, route.waypoint2, route.waypoint3
    path12 = cost_cache.astar_path(p1, p2)
    path23 = cost_cache.astar_path(p2, p3)
    path31 = cost_cache.astar_path(p3, p1)
    d12 = _sum_edge_length(G, path12) if path12 else None
    d23 = _sum_edge_length(G, path23) if path23 else None
    d31 = _sum_edge_length(G, path31) if path31 else None

    angle_diff_deg = None
    p1_data, p2_data, p3_data = G.nodes[p1], G.nodes[p2], G.nodes[p3]
    if all(k in d for d in (p1_data, p2_data, p3_data) for k in ("lat", "lon")):
        bearing_p2 = _bearing_rad(p1_data["lat"], p1_data["lon"], p2_data["lat"], p2_data["lon"])
        bearing_p3 = _bearing_rad(p1_data["lat"], p1_data["lon"], p3_data["lat"], p3_data["lon"])
        angle_diff_deg = math.degrees(_angular_separation_rad(bearing_p2, bearing_p3))

    balance_ratio = None
    if d12 is not None and d23 is not None and d31 is not None:
        largest = max(d12, d23, d31)
        balance_ratio = (min(d12, d23, d31) / largest) if largest > 0 else None

    degenerate = is_degenerate_loop_route(route.repeated_edge_ratio, d23, target_m, balance_ratio)

    return RouteGeometryMetrics(
        segment_p1_p2_m=d12,
        segment_p2_p3_m=d23,
        segment_p3_p1_m=d31,
        repeated_edge_ratio=route.repeated_edge_ratio,
        waypoint_separation_m=d23,
        waypoint_angle_diff_deg=angle_diff_deg,
        segment_balance_ratio=balance_ratio,
        is_degenerate_loop=degenerate,
    )


@dataclass(frozen=True)
class ConstructionResult:
    """construct_initial_route()의 반환값. route는 완주된 경로(실패 시 None). p1은
    pool_result.pool_nodes에 애초에 포함되지 않으므로(waypoint_pool.py), p2/p3가
    start_node와 같아지는 퇴화 사례는 후보 목록 단계에서 이미 불가능하다.

    had_valid_waypoint_pair는 최소거리(min_waypoint_separation_ratio) 조건을 만족하는
    (p2,p3) 조합을 이번 호출에서 최소 1개라도 찾았는지(=rcl3가 비지 않았는지)를 표시한다
    — route가 None이더라도(예: BuildCycleRoute의 A* 연결 실패) 조합 자체는 찾았을 수
    있으므로 route 유무와는 독립적인 신호다. 엔진의 find_path()가 GRASP 반복 전체에서
    이 값을 OR로 누적해, 최종 selection_status가 NO_VALID_WAYPOINT_PAIR인지
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
    """GRASP 구축 단계 — 3개 엔진(local/VND/VNS)이 동일하게 사용한다."""
    rcl2 = _rank_p2_candidates(pool_result, target_m)[: cfg.rcl_size]
    if not rcl2:
        return ConstructionResult(route=None, had_valid_waypoint_pair=False)
    p2 = rng.choice(rcl2)

    rcl3 = _rank_p3_candidates(G, pool_result, start_node, p2, target_m, cfg)[: cfg.rcl_size]
    if not rcl3:
        return ConstructionResult(route=None, had_valid_waypoint_pair=False)
    p3 = rng.choice(rcl3)

    route = BuildCycleRoute(G, cost_cache, start_node, p2, p3)
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
    """WaypointReplacement 이웃: waypoint2 또는 waypoint3를 다른 풀 후보로 교체한다.
    각 방향 모두 상위 rcl_size개 후보로 탐색 폭을 제한한다(랭킹 자체는 저렴하지만,
    각 후보마다 BuildCycleRoute의 실제 A* 3회는 비용이 있으므로 그 호출 횟수를 제한)."""
    for c in _rank_p2_candidates(pool_result, target_m, exclude=frozenset({route.waypoint3}))[: cfg.rcl_size]:
        if c == route.waypoint2:
            continue
        candidate = BuildCycleRoute(G, cost_cache, start_node, c, route.waypoint3)
        if candidate is not None:
            yield candidate

    for c in _rank_p3_candidates(
        G, pool_result, start_node, route.waypoint2, target_m, cfg,
        exclude=frozenset({route.waypoint3}),
    )[: cfg.rcl_size]:
        candidate = BuildCycleRoute(G, cost_cache, start_node, route.waypoint2, c)
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
    """WaypointPairReplacement 이웃: waypoint2·waypoint3 조합을 함께 바꾼다. 전체
    조합(O(rcl×rcl))은 비용이 커질 수 있어 양쪽 다 RCL 크기로 제한한다."""
    for p2 in _rank_p2_candidates(pool_result, target_m)[: cfg.rcl_size]:
        for p3 in _rank_p3_candidates(G, pool_result, start_node, p2, target_m, cfg)[: cfg.rcl_size]:
            if p2 == route.waypoint2 and p3 == route.waypoint3:
                continue
            candidate = BuildCycleRoute(G, cost_cache, start_node, p2, p3)
            if candidate is not None:
                yield candidate


def alternative_segment_neighbors(*args, **kwargs):
    """VND 이웃 3(AlternativeSegment): 같은 경유지 조합을 유지하면서 한 구간의 대체 A*
    경로를 탐색. **1차 구현에서는 비활성화**됨 — A*가 동일한 두 노드 사이에 항상 하나의
    경로만 반환하는 현재 구조를 확장해야 하므로(요청서 §8), circular_grasp_waypoint_vnd.py의
    이웃 목록에 등록하지 않는다."""
    raise NotImplementedError("AlternativeSegment는 1차 구현에서 비활성화되어 있습니다.")
