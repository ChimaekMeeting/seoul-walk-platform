import networkx as nx
from typing import Callable, Optional, List
import logging

from src.route_engine.engines.path_utils import PathUtils, _RETURN_REVISIT_PENALTY
from src.interfaces.schema.walk_schema import (
    WalkMode,
    WalkRouteStatus,
    WalkRouteResponse
)
from src.schema.route_schema import OnewayRouteInput, Weights
from src.route_engine.scoring.scoring_engine import WeightedEdgeCost
from src.route_engine.alt_runtime import get_alt_heuristic, get_alt_info
from src.config.logging import log_unexpected_error

logger = logging.getLogger(__name__)

class OnewayAstarEngine:
    def __init__(
        self,
        inp: OnewayRouteInput,
        G: nx.Graph,
        custom_weights: Optional[Weights] = None,
        visited_nodes: Optional[set] = None,
        heuristic: Optional[Callable[[int, int], float]] = None,
        cost_context: Optional[WeightedEdgeCost] = None,
    ):
        self.inp           = inp
        self.G             = G  # custom_score를 그래프에 쓰지 않으므로 copy() 불필요
        self.utils         = PathUtils(self.G)
        self.mode          = WalkMode.ONEWAY_SHORTEST
        self.weights       = custom_weights if custom_weights is not None else Weights()
        self.scoring_mode  = "general"
        # 거리 전용 weight. path_cost()의 기준이자, 가중 탐색의 물리 최단 비교 기준이다.
        # 항상 이 값을 유지한다(cost_context가 있어도 교체하지 않는다).
        self._distance_weight = self._make_distance_weight()
        # 실제 탐색에 쓰는 weight. cost_context가 활성 상태면 그쪽 가중 비용을 쓴다.
        # RouteService의 oneway_shortest는 cost_context를 넘기지 않으므로 물리 최단을
        # 유지하고, WaypointComposerEngine이 leg 엔진으로 쓸 때만 가중 비용이 주입된다.
        self.cost_context = cost_context if (cost_context and cost_context.enabled) else None
        self._weight_fn = self.cost_context.weight if self.cost_context else self._distance_weight
        # 이전 벤치마크 어댑터가 채우던 레거시 필드다. 엔진은 직접 edge 속성을 읽으므로
        # 요청마다 전체 간선 lookup을 만들 필요가 없고, 호환을 위해 빈 dict만 둔다.
        self._score_lookup: dict = {}
        # WaypointComposerEngine이 leg 간 경로 겹침을 페널티로 방지할 때 채워줌. 기본(빈 set)이면 기존 동작과 동일.
        self.visited_nodes = visited_nodes or set()
        self.last_path_nodes: list[int] = []  # 가장 최근 run()이 실제로 사용한 노드열(WaypointComposerEngine이 다음 leg의 visited_nodes 누적에 사용)
        # OnewayBeamEngine과 인터페이스를 맞추기 위한 필드. A*는 항상 후보가 1개뿐이라
        # 실질적으로 [last_path_nodes]와 같지만, WaypointComposerEngine이 leg 엔진 종류와
        # 무관하게 같은 방식으로 후보별 노드열을 조회할 수 있게 해준다.
        self.last_path_nodes_by_candidate: list[list[int]] = []
        # 휴리스틱 선택 순서: 명시 인자 > 그래프에 부착된 ALT > 기존 Haversine.
        # 셋 다 admissible하므로 어느 것을 써도 반환 경로의 최적성은 같다 — 바뀌는 것은
        # 탐색 속도뿐이다(docs/route_engine/README.md "ALT 서비스 연결" 절).
        # heuristic 인자는 배포 코드에 남는 정식 인자다. None이면 기존 동작. 시각화·벤치마크가 넘긴다.
        if heuristic is not None:
            self._active_heuristic = heuristic
            self.heuristic_name = "alt_injected"
        else:
            attached = get_alt_heuristic(G)
            if attached is not None:
                info = get_alt_info(G) or {}
                self._active_heuristic = attached
                self.heuristic_name = f"alt_{info.get('method', 'unknown')}"
            else:
                self._active_heuristic = self._heuristic
                self.heuristic_name = "haversine"

    def run(self) -> List[WalkRouteResponse]:
        """
        A* 최단 경로를 생성합니다.
        """
        logger.info(
            f"최단 경로 생성 엔진(A*)을 시작합니다: scoring_mode={self.scoring_mode}, "
            f"weights={self.weights}, heuristic={self.heuristic_name}, "
            f"cost={'weighted' if self.cost_context else 'distance'}"
        )

        # 출발 노드와 도착 노드 탐색
        start = self.utils.find_nearest_node(self.inp.start_lat, self.inp.start_lon)
        end   = self.utils.find_nearest_node(self.inp.end_lat,   self.inp.end_lon)

        if start is None:
            logger.warning("출발 노드를 찾지 못했습니다.")
            return [WalkRouteResponse(
                status=WalkRouteStatus.NO_NEAREST_START_NODE,
                mode=self.mode, coordinates=[], total_km=0.0,
            )]

        if end is None:
            logger.warning("도착 노드를 찾지 못했습니다.")
            return [WalkRouteResponse(
                status=WalkRouteStatus.NO_NEAREST_END_NODE,
                mode=self.mode, coordinates=[], total_km=0.0,
            )]

        # 경로 생성 (경로 후보가 리스트에 감싸져서 반환됨)
        candidates = self.find_path(start, end)

        if not candidates:
            logger.warning("경로가 비어 있습니다.")
            return [WalkRouteResponse(
                status=WalkRouteStatus.NO_PATH,
                mode=self.mode, coordinates=[], total_km=0.0,
            )]

        nodes     = candidates[0]                          # 경로 1개만 사용
        self.last_path_nodes = nodes
        self.last_path_nodes_by_candidate = [nodes]
        coords    = self.utils.extract_coordinates(nodes)
        total_m   = self.utils.calc_distance(nodes)
        total_km = round(total_m / 1000, 2)

        logger.info(f"total_km: {total_km}")

        return [WalkRouteResponse(
            status          = WalkRouteStatus.SUCCESS if coords else WalkRouteStatus.NO_PATH,
            mode            = self.mode,
            coordinates     = coords,
            total_km        = total_km,
        )]

    def find_path(self, start: int, end: int) -> list[list[int]]:
        """
        A* 알고리즘으로 최단 경로 노드 목록을 반환합니다.
        """
        try:
            return [nx.astar_path(
                self.G, start, end,
                heuristic=self._active_heuristic,
                weight=self._build_search_weight(end),
            )]
        except nx.NetworkXNoPath:
            logger.warning("출발-도착 노드 사이에 연결된 경로가 없습니다")
            return []
        except Exception as exc:
            log_unexpected_error(logger, "astar_path_error", exc)
            return []

    def _build_search_weight(self, end: int):
        """탐색에 넘길 weight 콜러블. 기본 비용(거리 또는 가중) 위에 재방문 페널티를 곱한다.

        PathUtils.connect_to와 동일한 패턴: 도착지 자신은 페널티 대상에서 제외한다.
        이 페널티는 비용을 늘리기만 하므로(배수 >= 1) 페널티 없는 거리로 만든 ALT
        하한도 여전히 실제 비용 이하다 — 즉 ALT 휴리스틱은 visited_nodes가 있어도,
        가중 비용을 써도 admissible하다(가중 비용 >= length이므로). Haversine이
        admissible한 근거와 같은 구조다.
        """
        def _weight(u, v, d):
            base = self._weight_fn(u, v, d)
            if v in self.visited_nodes and v != end:
                return base * _RETURN_REVISIT_PENALTY
            return base

        return _weight

    def path_cost(self, path: list[int]) -> float:
        """경로(노드 리스트)의 누적 거리(m).

        cost_context가 주입돼 탐색이 가중 비용으로 돌았더라도 **항상 거리**를 돌려준다
        — 벤치마크가 엔진끼리 비교하는 기준이라 요청 가중치에 따라 단위가 바뀌면
        비교가 조용히 깨진다. 가중 비용 합이 필요하면 weighted_path_cost()를 쓴다.
        """
        return self._sum_along(path, self._distance_weight)

    def weighted_path_cost(self, path: list[int]) -> float:
        """실제 탐색에 쓴 비용의 합. cost_context가 없으면 path_cost()와 같다."""
        return self._sum_along(path, self._weight_fn)

    def _sum_along(self, path: list[int], weight_fn) -> float:
        return sum(
            weight_fn(path[i], path[i + 1], self.G[path[i]][path[i + 1]])
            for i in range(len(path) - 1)
        )

    @staticmethod
    def _make_distance_weight():
        """length만 보는 weight 콜러블.

        기존 compute_distance_only_lookup()과 값이 완전히 같도록 맞췄다 — 누락된
        length는 1.0, 1m 미만은 1.0으로 올림(scoring_engine._build_feature_cache의
        max(1.0, length)와 동일). 달라진 것은 요청마다 2*E 크기 lookup dict를 만들지
        않고 A*가 확인한 edge에서 바로 읽는다는 점뿐이다.
        """
        def _weight(u, v, d):
            return max(1.0, float(d.get("length", 1.0) or 1.0))

        return _weight

    def _heuristic(self, node: int, target: int) -> float:
        """
        A* 휴리스틱: 두 좌표 사이의 Haversine 직선거리(m).
        weight가 거리(length) 그대로이므로 직선거리 ≤ 실제 도로망 거리(삼각부등식)가
        항상 성립해 별도 보정(min_ratio) 없이 admissible하다.
        """
        n = self.G.nodes[node]
        t = self.G.nodes[target]
        return self.utils._haversine_m(n.get("lat", 0), n.get("lon", 0), t.get("lat", 0), t.get("lon", 0))
