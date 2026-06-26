import logging
import math

from geoalchemy2.elements import WKTElement

from src.repository.network.edge_repository import EdgeRepository
from src.repository.network.node_repository import NodeRepository

logger = logging.getLogger(__name__)


class CollectorUtils:

    @staticmethod
    def make_point(lat: float, lon: float) -> WKTElement:
        return WKTElement(f"POINT({lon} {lat})", srid=4326)

    @staticmethod
    def register_nodes(
        records: list[dict],
        node_type: str,
        name_key: str = "name",
    ) -> dict[str, int]:
        """
        records를 walk_nodes에 등록하고 {name: node_id} 매핑을 반환합니다.
        각 record에는 'geom' 키가 있어야 합니다.
        """
        base_id = NodeRepository.get_max_node_id()
        nodes = [
            {
                "node_id":        base_id + i + 1,
                "node_type":      node_type,
                "is_underground": False,
                "is_overpass":    False,
                "geom":           rec["geom"],
            }
            for i, rec in enumerate(records)
        ]
        NodeRepository.save_all(nodes)
        logger.debug("walk_nodes에 %s 노드 %d개 등록 (base_id=%d)", node_type, len(nodes), base_id)
        return {rec[name_key]: base_id + i + 1 for i, rec in enumerate(records)}

    @staticmethod
    def update_edge_scores(score_column: str, h3_counts: dict[str, int]) -> None:
        """
        H3 카운트 기반 로그 정규화로 walk_edges의 score 컬럼을 업데이트합니다.
        정규화 공식: log(count+1) / max_log → 범위 0.0~1.0
        """
        edge_h3_rows = EdgeRepository.get_link_h3_cells()
        if not edge_h3_rows:
            logger.warning("walk_edges 데이터 없음 — %s 업데이트 건너뜀", score_column)
            return
        logger.debug("%s: H3 셀 %d개, 엣지 %d개", score_column, len(h3_counts), len(edge_h3_rows))
        log_vals = [math.log(h3_counts.get(row.h3_cell, 0) + 1) for row in edge_h3_rows]
        max_log = max(log_vals) or 1.0
        updates = [
            {"link_id": row.link_id, score_column: log_vals[i] / max_log}
            for i, row in enumerate(edge_h3_rows)
        ]
        EdgeRepository.update_scores(updates)
        logger.info("%s 업데이트 완료: %d건", score_column, len(updates))
