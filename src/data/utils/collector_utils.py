import math

from geoalchemy2.elements import WKTElement

from src.repository.route.edge_repository import EdgeRepository
from src.repository.route.node_repository import NodeRepository


class CollectorUtils:

    @staticmethod
    def make_point(lat: float, lng: float) -> WKTElement:
        return WKTElement(f"POINT({lng} {lat})", srid=4326)

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
        return {rec[name_key]: base_id + i + 1 for i, rec in enumerate(records)}

    @staticmethod
    def update_edge_scores(score_column: str, h3_counts: dict[str, int]) -> None:
        """
        H3 카운트 기반 로그 정규화로 walk_edges의 score 컬럼을 업데이트합니다.
        정규화 공식: 1.0 + log(count+1) / max_log → 범위 1.0~2.0
        """
        edge_h3_rows = EdgeRepository.get_link_h3_cells()
        if not edge_h3_rows:
            print(f"  walk_edges 데이터 없음 — {score_column} 업데이트 건너뜀")
            return
        log_vals = [math.log(h3_counts.get(row.h3_cell, 0) + 1) for row in edge_h3_rows]
        max_log = max(log_vals) or 1.0
        updates = [
            {"link_id": row.link_id, score_column: 1.0 + log_vals[i] / max_log}
            for i, row in enumerate(edge_h3_rows)
        ]
        EdgeRepository.update_scores(updates)
        print(f"  {score_column} 업데이트 완료: {len(updates)}건")
