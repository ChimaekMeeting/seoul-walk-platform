from typing import List

from sqlalchemy import func, select, insert, text

from src.database.postgresql import get_postgresql_db, engine
from src.entity.layer.nature_layer import NaturePoint


class NatureRepository:
    @staticmethod
    def truncate():
        """
        poi_layer 테이블의 모든 데이터를 초기화합니다.
        시퀀스(ID)도 함께 리셋하며, 연관 테이블에 CASCADE 적용합니다.
        """
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE poi_layer RESTART IDENTITY CASCADE"))

    @staticmethod
    def save_all(records: List[dict]):
        """
        자연/녹지 시설물 데이터를 poi_layer에 벌크 저장합니다.

        Args:
            records : 저장할 POI 딕셔너리 목록.
        """
        with get_postgresql_db() as db:
            db.execute(insert(NaturePoint), records)
            db.commit()

    @staticmethod
    def get_nature_h3_counts() -> dict[str, int]:
        """
        H3 셀(resolution 9)별 자연/녹지 시설물 개수를 반환합니다.

        Returns:
            dict[str, int]: {h3_cell: count} 형태의 딕셔너리.
        """
        with get_postgresql_db() as db:
            h3_expr = func.h3_lat_lng_to_cell(NaturePoint.geom, 9)
            rows = db.execute(
                select(h3_expr.label("h3_cell"), func.count().label("cnt"))
                .group_by(h3_expr)
            ).fetchall()
            return {row.h3_cell: row.cnt for row in rows}
