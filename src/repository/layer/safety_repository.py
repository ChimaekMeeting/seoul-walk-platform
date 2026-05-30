from typing import List

from sqlalchemy import func, select, insert, text

from src.database.postgresql import get_postgresql_db, engine
from src.entity.layer.safety_layer import SafetyLayer
from src.repository.utils import RepositoryUtils
from collections import Counter


class SafetyRepository:
    @staticmethod
    def truncate():
        """
        safety_layer 테이블의 모든 데이터를 초기화합니다.
        시퀀스(ID)도 함께 리셋하며, 연관 테이블에 CASCADE 적용합니다.
        """
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE safety_layer RESTART IDENTITY CASCADE"))

    @staticmethod
    def save_all(records: List[dict]):
        """
        안전 시설물 데이터를 safety_layer에 벌크 저장합니다.

        Args:
            records : 저장할 안전 시설물 딕셔너리 목록.
        """
        with get_postgresql_db() as db:
            db.execute(insert(SafetyLayer), records)
            db.commit()

    @staticmethod
    def get_safety_h3_counts() -> dict[str, int]:
        """
        H3 셀(resolution 9)별 SafetyLayer 개수를 반환합니다.

        Returns:
            dict[str, int]: {h3_cell: count} 형태의 딕셔너리.
        """
        lat_expr, lng_expr = RepositoryUtils.geom_centroid_lat_lng(SafetyLayer.geom)
        with get_postgresql_db() as db:
            rows = db.execute(
                select(lat_expr.label("lat"), lng_expr.label("lng"))
            ).fetchall()
        cells = (RepositoryUtils.lat_lng_to_h3(row.lat, row.lng) for row in rows)
        return dict(Counter(cells))
