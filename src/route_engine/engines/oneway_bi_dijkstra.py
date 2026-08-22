# src/route_engine/engines/oneway_bi_dijkstra.py
import logging

import networkx as nx

from src.route_engine.engines.dijkstra import OnewayDijkstraEngine

logger = logging.getLogger(__name__)


class OnewayBidirectionalDijkstraEngine(OnewayDijkstraEngine):
    """OnewayDijkstraEngine과 동일한 인터페이스, 탐색만 양방향 Dijkstra(nx.bidirectional_dijkstra)로 교체."""

    def find_path(self, start: int, end: int) -> list[int]:
        """
        양방향 Dijkstra 알고리즘으로 최단 경로 노드 목록을 반환합니다.
        """
        try:
            _, path = nx.bidirectional_dijkstra(self.G, start, end, weight=self._weight_fn)
            return path
        except nx.NetworkXNoPath:
            logger.warning("출발-도착 노드 사이에 연결된 경로가 없습니다")
            return []
        except Exception:
            logger.exception("최단 경로 생성에 실패했습니다")
            return []
