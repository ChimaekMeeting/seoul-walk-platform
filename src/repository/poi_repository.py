from sqlalchemy import func, select, insert
from src.database.postgresql import get_postgresql_db
from src.entity.poi_network import Landmark
from typing import List

class LandmarkRepository:
    @staticmethod
    def save_all(landmarks: List[dict]):
        with get_postgresql_db() as db:
            db.execute(insert(Landmark), landmarks)
            db.commit()

    @staticmethod
    def get_walk_node_id_by_name(name: str) -> int | None:
        with get_postgresql_db() as db:
            result = db.query(Landmark.walk_node_id).filter(Landmark.name == name).scalar()
            return result

    @staticmethod
    def update_walk_node_ids(name_to_node_id: dict[str, int]):
        with get_postgresql_db() as db:
            for name, node_id in name_to_node_id.items():
                db.query(Landmark).filter(Landmark.name == name).update({"walk_node_id": node_id})
            db.commit()

    @staticmethod
    def get_landmark_h3_counts() -> dict[str, int]:
        with get_postgresql_db() as db:
            h3_expr = func.h3_lat_lng_to_cell(Landmark.geom, 9)

            # h3_cell별 랜드마크 cnt
            rows = db.execute(
                select(h3_expr.label("h3_cell"), func.count().label("cnt"))
                .group_by(h3_expr)
            ).fetchall()
            return {row.h3_cell: row.cnt for row in rows}