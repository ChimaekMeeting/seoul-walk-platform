import networkx as nx
from typing import List, Optional
import logging

from src.route_engine.engines.path_utils import PathUtils
from src.interfaces.schema.walk_schema import (
    WalkMode,
    WalkRouteStatus,
    WalkRouteResponse
)
from src.schema.route_schema import OnewayRouteInput, Weights
from src.route_engine.scoring.scoring_engine import compute_distance_only_lookup
from src.config.logging import log_unexpected_error

logger = logging.getLogger(__name__)

class OnewayDijkstraEngine:
    def __init__(
        self,
        inp: OnewayRouteInput,
        G: nx.Graph,
        custom_weights: Optional[Weights] = None,
    ):
        self.inp           = inp
        self.G             = G  # custom_score를 그래프에 쓰지 않으므로 copy() 불필요
        self.utils         = PathUtils(self.G)
        self.mode          = WalkMode.ONEWAY_SHORTEST
        self.weights       = custom_weights if custom_weights is not None else Weights()
        self.scoring_mode  = "general"
        self._weight_fn    = None
        self._score_lookup: dict = {}

    def run(self) -> List[WalkRouteResponse]:
        """
        Dijkstra 최단 경로를 생성합니다.
        """
        logger.info(f"최단 경로 생성 엔진을 시작합니다: scoring_mode={self.scoring_mode}, weights={self.weights}")

        scored = compute_distance_only_lookup(self.G)
        self._weight_fn    = scored["weight"]
        self._score_lookup = scored["lookup"]

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

        nodes = self.find_path(start, end)

        if not nodes:
            logger.warning("경로가 비어 있습니다.")
            return [WalkRouteResponse(
                status=WalkRouteStatus.NO_PATH,
                mode=self.mode, coordinates=[], total_km=0.0,
            )]

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

    def find_path(self, start: int, end: int) -> list[int]:
        """
        Dijkstra 알고리즘으로 최단 경로 노드 목록을 반환합니다.
        """
        try:
            return nx.shortest_path(self.G, start, end, weight=self._weight_fn)
        except nx.NetworkXNoPath:
            logger.warning("출발-도착 노드 사이에 연결된 경로가 없습니다")
            return []
        except Exception as exc:
            log_unexpected_error(logger, "dijkstra_path_error", exc)
            return []

    def path_cost(self, path: list[int]) -> float:
        """경로(노드 리스트)의 누적 거리(m). 벤치마크 solver의 cost 계산용."""
        return sum(
            self._score_lookup.get((path[i], path[i + 1]), 1.0)
            for i in range(len(path) - 1)
        )
