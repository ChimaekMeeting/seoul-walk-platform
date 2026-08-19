import logging
import math

from geoalchemy2.elements import WKTElement

from src.repository.network.edge_repository import EdgeRepository

logger = logging.getLogger(__name__)


class CollectorUtils:

    @staticmethod
    def make_point(lat: float, lon: float) -> WKTElement:
        return WKTElement(f"POINT({lon} {lat})", srid=4326)

    @staticmethod
    def update_edge_scores(score_column: str, edge_counts: dict[int, int]) -> None:
        """
        Edge 반경 기반 카운트를 로그 정규화해 walk_edges의 score 컬럼을 업데이트합니다.
        정규화 공식: log(count+1) / max_log → 범위 0.0~1.0
        """
        link_ids = EdgeRepository.get_all_link_ids()
        if not link_ids:
            logger.warning("walk_edges 데이터 없음 — %s 업데이트 건너뜀", score_column)
            return
        logger.debug("%s: feature가 있는 엣지 %d개, 엣지 %d개", score_column, len(edge_counts), len(link_ids))
        log_vals = [math.log(edge_counts.get(link_id, 0) + 1) for link_id in link_ids]
        max_log = max(log_vals) or 1.0
        updates = [
            {"link_id": link_id, score_column: log_vals[i] / max_log}
            for i, link_id in enumerate(link_ids)
        ]
        EdgeRepository.update_scores(updates)
        logger.info("%s 업데이트 완료: %d건", score_column, len(updates))
