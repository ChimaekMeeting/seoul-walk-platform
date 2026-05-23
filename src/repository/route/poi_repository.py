from sqlalchemy import func, select, insert, text
from src.database.postgresql import get_postgresql_db, engine
from src.entity.poi_network import Landmark, SafetyPoint, PoiPoint
from typing import List

class SafetyRepository:
    @staticmethod
    def truncate():
        """
        safety_layer 테이블의 모든 데이터를 초기화합니다.
        """
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE safety_layer RESTART IDENTITY CASCADE"))

    @staticmethod
    def save_all(records: List[dict]):
        """
        safety_layer에 안전 시설물 데이터를 벌크 저장합니다.
        """
        with get_postgresql_db() as db:
            db.execute(insert(SafetyPoint), records)
            db.commit()

    @staticmethod
    def get_safety_h3_counts() -> dict[str, int]:
        """H3 셀(resolution 9)별 SafetyPoint 개수를 반환합니다."""
        with get_postgresql_db() as db:
            h3_expr = func.h3_lat_lng_to_cell(SafetyPoint.geom, 9)
            rows = db.execute(
                select(h3_expr.label("h3_cell"), func.count().label("cnt"))
                .group_by(h3_expr)
            ).fetchall()
            return {row.h3_cell: row.cnt for row in rows}


class NatureRepository:
    @staticmethod
    def truncate():
        """
        poi_layer 테이블의 모든 데이터를 초기화합니다.
        """
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE poi_layer RESTART IDENTITY CASCADE"))

    @staticmethod
    def save_all(records: List[dict]):
        """
        poi_layer에 자연/녹지 시설물 데이터를 벌크 저장합니다.
        """
        with get_postgresql_db() as db:
            db.execute(insert(PoiPoint), records)
            db.commit()

    @staticmethod
    def get_nature_h3_counts() -> dict[str, int]:
        """H3 셀(resolution 9)별 자연/녹지 시설물 개수를 반환합니다."""
        with get_postgresql_db() as db:
            h3_expr = func.h3_lat_lng_to_cell(PoiPoint.geom, 9)
            rows = db.execute(
                select(h3_expr.label("h3_cell"), func.count().label("cnt"))
                .group_by(h3_expr)
            ).fetchall()
            return {row.h3_cell: row.cnt for row in rows}


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