from typing import List

from sqlalchemy import func, select, insert, update

from src.database.postgresql import get_postgresql_db
from src.entity.layer.landmark_layer import LandmarkLayer


class LandmarkRepository:
    @staticmethod
    def save_all(landmarks: List[dict]):
        """
        랜드마크 데이터를 landmark_layer에 벌크 저장합니다.

        Args:
            landmarks : 저장할 랜드마크 딕셔너리 목록.
        """
        with get_postgresql_db() as db:
            db.execute(insert(LandmarkLayer), landmarks)
            db.commit()

    @staticmethod
    def get_walk_node_id_by_name(name: str) -> int | None:
        """
        랜드마크 이름으로 연결된 walk_node_id를 반환합니다.

        Args:
            name : 조회할 랜드마크 이름.

        Returns:
            int | None: 연결된 walk_node_id. 없으면 None.
        """
        with get_postgresql_db() as db:
            return db.execute(
                select(LandmarkLayer.walk_node_id).where(LandmarkLayer.name == name)
            ).scalar_one_or_none()

    @staticmethod
    def update_walk_node_ids(name_to_node_id: dict[str, int]):
        """
        랜드마크 이름을 키로 walk_node_id를 일괄 업데이트합니다.

        Args:
            name_to_node_id : {랜드마크명: walk_node_id} 형태의 딕셔너리.
        """
        with get_postgresql_db() as db:
            for name, node_id in name_to_node_id.items():
                db.execute(
                    update(LandmarkLayer).where(LandmarkLayer.name == name).values(walk_node_id=node_id)
                )
            db.commit()

    @staticmethod
    def get_landmark_h3_counts() -> dict[str, int]:
        """
        H3 셀(resolution 9)별 랜드마크 개수를 반환합니다.

        Returns:
            dict[str, int]: {h3_cell: count} 형태의 딕셔너리.
        """
        with get_postgresql_db() as db:
            h3_expr = func.h3_lat_lng_to_cell(LandmarkLayer.geom, 9)
            rows = db.execute(
                select(h3_expr.label("h3_cell"), func.count().label("cnt"))
                .group_by(h3_expr)
            ).fetchall()
            return {row.h3_cell: row.cnt for row in rows}
