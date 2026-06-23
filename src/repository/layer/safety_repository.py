from typing import List

import pandas as pd
from sqlalchemy import func, select, insert

from src.database.postgresql import get_postgresql_db
from src.entity.layer.safety_layer import SafetyLayer
from src.repository.utils import RepositoryUtils
from collections import Counter


class SafetyRepository:
    @staticmethod
    def get(lat: float, lon: float, radius_m: int = 2000) -> pd.DataFrame:
        """
        반경 내 안전 시설물 포인트 전체를 조회합니다.
        safety_type(예: cctv, streetlight)을 category로 노출합니다.
        """
        return RepositoryUtils.fetch_nearby_points(
            SafetyLayer, lat, lon, radius_m, category_col=SafetyLayer.safety_type,
        )

    @staticmethod
    def is_populated() -> bool:
        with get_postgresql_db() as db:
            return db.execute(select(func.count()).select_from(SafetyLayer)).scalar() > 0

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
        lat_expr, lon_expr = RepositoryUtils.geom_centroid_lat_lon(SafetyLayer.geom)
        with get_postgresql_db() as db:
            rows = db.execute(
                select(lat_expr.label("lat"), lon_expr.label("lon"))
            ).fetchall()
        cells = (RepositoryUtils.lat_lon_to_h3(row.lat, row.lon) for row in rows)
        return dict(Counter(cells))
