"""
src/route_engine/engines/waypoint_pool.py

경유지 후보 풀 생성 — 거리링(distance ring) cutoff SSSP + 단일 풀.

p1(출발지) 기준 거리 전용(distance-only) cutoff SSSP를 1회 수행해, r_max(=target_m/2)
이내의 노드를 후보 풀로 수집한다. 이후 조합 개선 단계(beam/GRASP/지역탐색 등)가 이동
비용을 그때그때 재계산하지 않도록, 풀 내 노드 간 거리는 lazy 계산 + LRU 캐시로 제공한다
(WaypointPoolResult.distance() 참고).

r_max = target_m / 2 근거(삼각부등식, 논문 원문 확인):
Lewis & Corcoran, "Finding fixed-length circuits and cycles in undirected
edge-weighted graphs" (J. Heuristics, 2022) 원문:
    "any vertex v whose distance is more than k/2 units from the source can
    be removed from the graph since, in such cases, all s-v-circuits will be
    longer than k."
어떤 라운드트립이 노드 v를 지난다면, 그 경로 길이는 (p1→v 구간) + (v→p1 구간) 이상이고
각 구간은 최단경로(=dist(p1,v)) 이상이므로 총 길이 ≥ 2·dist(p1,v)가 항상 성립한다. 이
부등식은 경유지 개수(n)와 무관하게 성립하므로 n≥3 일반화에도 그대로 적용된다.

r_min(거리 하한)은 두지 않는다: 위 논문과 후속 논문(SN Comp Sci, 2024) 모두 하한 없이
r_max 이내 전체를 후보로 쓰고, 하한을 뒷받침하는 공식도 제시하지 않는다(2026-08-30
논문 원문 확인).

pairwise 거리를 lazy + 캐시로 두는 근거: 위 두 논문의 지역탐색(2024년 논문의 Algorithm
3/4, Pareto local search의 neighbourhood operator)도 매 이웃 연산마다 선택된 노드
u_i 기준으로 그때그때 도달 트리(BFS)를 계산하지, 전체 쌍을 사전에 다 계산해두지 않는다.
실제로 실제 그래프(노드 160,328개·엣지 223,927개) 벤치마크에서 전체 쌍 사전계산 방식은
target_km이 큰 경우(5~8km) pool 크기·pairwise 항목 수가 함께 급증해 MemoryError로
실패했다(2026-08-30 확인) — 이 문제를 피하기 위해 필요한 쌍만 그때그때 계산한다.

참고 논문:
- Lewis & Corcoran, J. Heuristics (2022) — r_max=k/2 cutoff SSSP 전처리 공식
- Lewis & Corcoran, SN Comp Sci (2024) — 단일 cutoff 영역에서 n=3~8 candidate pool 생성 검증,
  전체 쌍이 아니라 선택된 노드 기준으로 그때그때 계산하는 지역탐색 패턴
"""

import logging
from collections import OrderedDict

import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.scoring.scoring_engine import compute_distance_only_lookup

logger = logging.getLogger(__name__)

_DEFAULT_PAIRWISE_CACHE_ROWS: int = 256  # 캐시할 최대 소스 노드(행) 개수 — 논문 근거 없는 엔지니어링 기본값


class WaypointPoolResult:
    """
    경유지 후보 풀 생성 결과.

    pool_nodes: r_max(=target_m/2) 이내 후보 노드 ID 목록(p1 자신은 제외). 순수 노드 ID
        컬렉션이라, 조합 단계는 자신의 visited 집합과 집합 연산(예: 차집합)만으로 이미 쓴
        노드를 걸러낼 수 있다 — WaypointComposerEngine의 visited_nodes와 동일한 패턴.
    dist_from_p1: p1 -> 풀 노드 거리(m). {node_id: dist_m}
    r_max: 실제 적용된 cutoff 거리(m) = target_m / 2.

    풀 내 노드 간 거리는 pairwise 필드로 미리 다 계산해두지 않는다 — distance(u, v)를
    호출한 시점에 u를 소스로 하는 cutoff=r_max SSSP를 1회 계산해 그 행(row) 전체를
    캐시하고, 이후 같은 u에서의 조회는 캐시를 그대로 쓴다. 무방향 그래프이므로 반대
    방향(v를 소스로 하는 행)이 이미 캐시돼 있으면 그것도 그대로 재사용한다.
    """

    def __init__(
        self,
        pool_nodes: list[int],
        dist_from_p1: dict[int, float],
        r_max: float,
        G_band: nx.Graph,
        weight,
        cache_rows: int = _DEFAULT_PAIRWISE_CACHE_ROWS,
    ):
        self.pool_nodes = pool_nodes
        self.dist_from_p1 = dist_from_p1
        self.r_max = r_max
        self._pool_set = set(pool_nodes)
        self._G_band = G_band
        self._weight = weight
        self._cache_rows = cache_rows
        self._row_cache: "OrderedDict[int, dict[int, float]]" = OrderedDict()
        self._cache_hits = 0
        self._cache_misses = 0

    @property
    def cached_row_count(self) -> int:
        """지금까지 캐시된 소스 노드(행) 개수 — 벤치마크/진단용."""
        return len(self._row_cache)

    @property
    def cache_hits(self) -> int:
        """distance() 호출 중 이미 캐시된 행(정방향 또는 역방향)으로 응답한 횟수."""
        return self._cache_hits

    @property
    def cache_misses(self) -> int:
        """distance() 호출 중 새로 SSSP를 계산해야 했던 횟수(_DEFAULT_PAIRWISE_CACHE_ROWS 튜닝용)."""
        return self._cache_misses

    @property
    def cache_hit_ratio(self) -> float | None:
        """u == v로 즉시 반환된 호출은 분모에서 제외한다(캐시와 무관한 경로라서)."""
        total = self._cache_hits + self._cache_misses
        return round(self._cache_hits / total, 4) if total else None

    def distance(self, u: int, v: int) -> float | None:
        """
        풀 내 두 노드 u, v 사이의 거리(m)를 반환한다. r_max 이내로 도달 불가능하면
        None을 반환한다. u, v가 풀 노드가 아니면 ValueError를 던진다.
        """
        if u not in self._pool_set or v not in self._pool_set:
            raise ValueError(f"풀 노드가 아닙니다: u={u}, v={v}")
        if u == v:
            return 0.0

        row = self._row_cache.get(u)
        if row is not None:
            self._row_cache.move_to_end(u)
            self._cache_hits += 1
            return row.get(v)

        # 무방향 그래프이므로 반대 방향 행이 이미 캐시돼 있으면 새로 계산하지 않고 재사용
        reverse_row = self._row_cache.get(v)
        if reverse_row is not None:
            self._row_cache.move_to_end(v)
            self._cache_hits += 1
            return reverse_row.get(u)

        self._cache_misses += 1
        row = self._compute_row(u)
        self._row_cache[u] = row
        self._evict_if_needed()
        return row.get(v)

    def _compute_row(self, u: int) -> dict[int, float]:
        dist_from_u = nx.single_source_dijkstra_path_length(
            self._G_band, u, cutoff=self.r_max, weight=self._weight
        )
        return {v: d for v, d in dist_from_u.items() if v != u and v in self._pool_set}

    def _evict_if_needed(self) -> None:
        while len(self._row_cache) > self._cache_rows:
            self._row_cache.popitem(last=False)  # 가장 오래 쓰이지 않은 행 제거(LRU)


class WaypointPoolResultTwoPoint(WaypointPoolResult):
    """
    편도(p1→p2) 경유지 후보 풀 생성 결과.

    p1·p2 서로 다른 두 지점을 초점으로 하는 타원 조건
    dist(p1,v) + dist(v,p2) <= budget_m(=target_m+slack_m)을 만족하는 노드만
    pool_nodes에 담는다. 각 소스의 cutoff SSSP(반경 budget_m)는 후보 도메인을 좁히는
    전처리일 뿐이고, 실제 채택 기준은 항상 이 합 조건 하나다 — "두 cutoff 영역이
    겹치는가"는 판단 기준이 아니다(두 영역은 budget_m >= dist(p1,p2)/2부터 겹치기
    시작하지만, 그 안의 노드가 합 조건까지 만족한다는 보장은 없다 — 실제로 후보가
    하나라도 존재하려면 budget_m >= dist(p1,p2)가 필요하다. build_pool_two_point()의
    infeasible 판정 참고).

    순환(WaypointPoolResult)의 r_max=target_m/2 원 조건은 p1=p2인 퇴화 케이스이고,
    편도는 p1≠p2이므로 원 조건을 그대로 전용할 수 없다.

    distance()의 lazy+LRU 캐시, G_band 서브그래프 구조는 부모 클래스를 그대로 상속해
    재사용한다. 부모의 r_max 필드는 여기서는 budget_m으로 재해석된다: 왕복은 소스
    하나에서 절반만 가면 되지만, 편도는 한쪽 구간이 0에 가까우면 다른 쪽이 budget_m
    전체를 써야 하므로 각 소스의 cutoff 자체가 target_m/2가 아니라 budget_m이어야
    한다. distance(u,v)의 lazy SSSP도 이 budget_m을 cutoff로 쓴다 — p1→u→v→p2
    경로에서 dist(u,v) <= budget_m - dist(p1,u) - dist(v,p2) <= budget_m이 항상
    성립하므로, budget_m은 잘라내도 안전한(false negative 없는) 상한이다.
    """

    def __init__(
        self,
        pool_nodes: list[int],
        dist_from_p1: dict[int, float],
        dist_from_p2: dict[int, float],
        p1: int,
        p2: int,
        target_m: float,
        budget_m: float,
        G_band: nx.Graph,
        weight,
        cache_rows: int = _DEFAULT_PAIRWISE_CACHE_ROWS,
    ):
        super().__init__(
            pool_nodes=pool_nodes,
            dist_from_p1=dist_from_p1,
            r_max=budget_m,
            G_band=G_band,
            weight=weight,
            cache_rows=cache_rows,
        )
        self.dist_from_p2 = dist_from_p2
        self.p1 = p1
        self.p2 = p2
        self.target_m = target_m
        self.budget_m = budget_m


class WaypointPoolGenerator:
    """
    p1 기준 cutoff SSSP로 거리 밴드 후보 풀을 만든다. 새 경로 탐색 알고리즘이 아니라
    이후 조합 단계(beam/GRASP/지역탐색)가 쓸 입력을 준비하는 전처리 단계이므로, 다른
    engines/*.py 엔진과 달리 WalkRouteResponse를 반환하지 않는다(경로 자체를 만들지
    않음 — 그래서 engines/__init__.py에도 등록하지 않는다. 아직 소비하는 조합 단계가
    없어 route_service.py 연동도 하지 않는다).
    """

    def __init__(self, G: nx.Graph):
        self.G = G  # 조회 전용(mutate 없음)이므로 copy 안 함
        self.utils = PathUtils(self.G)

    def build_pool(
        self,
        p1_lat: float,
        p1_lon: float,
        target_km: float,
        pairwise_cache_rows: int = _DEFAULT_PAIRWISE_CACHE_ROWS,
    ) -> WaypointPoolResult | None:
        """
        p1 좌표와 목표 총 거리(target_km)로 경유지 후보 풀을 만든다.
        p1의 최근접 노드를 못 찾으면 None을 반환한다.
        """
        p1 = self.utils.find_nearest_node_with_expansion(p1_lat, p1_lon)
        if p1 is None:
            logger.warning("p1 기준 노드를 찾지 못했습니다.")
            return None

        r_max = (target_km * 1000) / 2
        weight = compute_distance_only_lookup(self.G)["weight"]

        # cutoff SSSP 1회 — r_max 밖의 노드는 애초에 순회 안 함
        dist_from_p1 = nx.single_source_dijkstra_path_length(
            self.G, p1, cutoff=r_max, weight=weight
        )
        pool_nodes = [v for v in dist_from_p1 if v != p1]

        # r_max 밖의 노드는 어떤 라운드트립에도 포함될 수 없으므로(위 docstring의
        # 삼각부등식 근거), 이후 distance()의 lazy SSSP도 원본 그래프 전체가 아니라
        # 이 유도 부분그래프에서만 돌려 탐색 범위를 줄인다.
        G_band = self.G.subgraph(dist_from_p1.keys())

        logger.info(
            "경유지 후보 풀 생성 완료: 노드 %d개, r_max=%.1fm (pairwise는 lazy 계산)",
            len(pool_nodes), r_max,
        )

        return WaypointPoolResult(
            pool_nodes=pool_nodes,
            dist_from_p1={v: dist_from_p1[v] for v in pool_nodes},
            r_max=r_max,
            G_band=G_band,
            weight=weight,
            cache_rows=pairwise_cache_rows,
        )

    def build_pool_two_point(
        self,
        p1_lat: float,
        p1_lon: float,
        p2_lat: float,
        p2_lon: float,
        target_km: float,
        slack_m: float = 0.0,
        pairwise_cache_rows: int = _DEFAULT_PAIRWISE_CACHE_ROWS,
    ) -> WaypointPoolResultTwoPoint | None:
        """
        p1(출발지)·p2(목적지) 좌표와 목표 총 거리(target_km)로 편도 경유지 후보 풀을 만든다.

        dist(p1,v) + dist(v,p2) <= budget_m(=target_km*1000+slack_m)을 만족하는 노드만
        후보로 남긴다 — p1·p2를 초점으로 하는 타원 조건이며, build_pool()의
        r_max=target_m/2 원 조건이 p1=p2인 퇴화 케이스임을 일반화한 것이다
        (WaypointPoolResultTwoPoint 문서 참고).

        p1 또는 p2의 최근접 노드를 못 찾거나, budget_m이 dist(p1,p2)(합 조건을 만족하는
        노드가 하나라도 존재하기 위한 최소 거리)보다 짧아 애초에 실현 불가능하면 None을
        반환한다. "두 cutoff 영역이 겹치는가"가 아니라 이 최소 거리 하나로만 판단한다.
        """
        p1 = self.utils.find_nearest_node_with_expansion(p1_lat, p1_lon)
        p2 = self.utils.find_nearest_node_with_expansion(p2_lat, p2_lon)
        if p1 is None or p2 is None:
            logger.warning("p1 또는 p2 기준 노드를 찾지 못했습니다.")
            return None

        target_m = target_km * 1000
        budget_m = target_m + slack_m
        weight = compute_distance_only_lookup(self.G)["weight"]

        # cutoff SSSP 2회 — budget_m 밖의 노드는 어느 쪽이든 합 조건을 만족할 수 없으므로
        # 애초에 순회 안 함. slack_m만큼 사후 필터(budget_m)만 늘리고 cutoff는 target_m에
        # 묶어두면, slack 덕분에 포함돼야 할 노드가 SSSP 단계에서부터 잘려나간다 — 반드시
        # 같은 budget_m을 cutoff로 써야 한다. 왕복(r_max=target_m/2)과 달리 편도는 각
        # 소스의 cutoff 자체가 (거의) target_m 전체여야 한다(클래스 docstring 삼각부등식
        # 참고).
        dist_from_p1 = nx.single_source_dijkstra_path_length(
            self.G, p1, cutoff=budget_m, weight=weight
        )
        dist_from_p2 = nx.single_source_dijkstra_path_length(
            self.G, p2, cutoff=budget_m, weight=weight
        )

        if p2 not in dist_from_p1:
            # dist(p1,p2) > budget_m이면 p1→p2 직행조차 budget_m을 넘어, 합 조건을
            # 만족하는 노드가 하나도 있을 수 없다(최소 실현 가능 target_km = dist(p1,p2) - slack_m/1000).
            logger.warning(
                "target_km(+slack_m)이 p1-p2 최단거리보다 짧아 편도 풀을 생성할 수 없습니다: "
                "budget_m=%.1f",
                budget_m,
            )
            return None

        pool_nodes = [
            v for v, d1 in dist_from_p1.items()
            if v != p1 and v != p2
            and (d2 := dist_from_p2.get(v)) is not None
            and d1 + d2 <= budget_m
        ]

        # 두 SSSP 합집합 밖의 노드는 위 필터를 애초에 통과할 수 없으므로, 이후 pairwise
        # lazy SSSP도 이 유도 부분그래프 안에서만 돈다.
        band_nodes = set(dist_from_p1.keys()) | set(dist_from_p2.keys())
        G_band = self.G.subgraph(band_nodes)

        logger.info(
            "편도 경유지 후보 풀 생성 완료: 노드 %d개, target_m=%.1f, budget_m=%.1f "
            "(pairwise는 lazy 계산)",
            len(pool_nodes), target_m, budget_m,
        )

        return WaypointPoolResultTwoPoint(
            pool_nodes=pool_nodes,
            dist_from_p1={v: dist_from_p1[v] for v in pool_nodes},
            dist_from_p2={v: dist_from_p2[v] for v in pool_nodes},
            p1=p1,
            p2=p2,
            target_m=target_m,
            budget_m=budget_m,
            G_band=G_band,
            weight=weight,
            cache_rows=pairwise_cache_rows,
        )
