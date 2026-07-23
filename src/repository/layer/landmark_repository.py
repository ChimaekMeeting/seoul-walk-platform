from collections import Counter
from typing import List

import pandas as pd
from shapely.wkt import loads as wkt_loads
from sqlalchemy import func, select, insert

from src.database.postgresql import get_postgresql_db
from src.entity.layer.landmark_layer import LandmarkLayer
from src.repository.utils import RepositoryUtils


class LandmarkRepository:
    @staticmethod
    def get(lat: float, lon: float, radius_m: int = 2000) -> pd.DataFrame:
        """
        반경 내 랜드마크 포인트를 조회합니다. (타입 필터 없음)
        """
        return RepositoryUtils.fetch_nearby_points(LandmarkLayer, lat, lon, radius_m)

    @staticmethod
    def save_all(landmarks: List[dict]):
        """
        랜드마크 데이터를 landmark_layer에 벌크 저장합니다. 이미 같은 경위도가 있으면 스킵합니다.
        """
        if not landmarks:
            return
        with get_postgresql_db() as db:
            rows = db.execute(
                select(func.ST_Y(LandmarkLayer.geom).label("lat"), func.ST_X(LandmarkLayer.geom).label("lon"))
            ).fetchall()
            existing = {(round(float(r.lat), 6), round(float(r.lon), 6)) for r in rows}
            new_records = []
            for r in landmarks:
                pt = wkt_loads(r["geom"].desc)
                if (round(pt.y, 6), round(pt.x, 6)) not in existing:
                    new_records.append(r)
            if not new_records:
                return
            db.execute(insert(LandmarkLayer), new_records)
            db.commit()

    @staticmethod
    def get_landmark_h3_counts() -> dict[str, int]:
        """
        H3 셀(resolution 9)별 랜드마크 개수를 반환합니다.

        Returns:
            dict[str, int]: {h3_cell: count} 형태의 딕셔너리.
        """
        lat_expr, lon_expr = RepositoryUtils.geom_centroid_lat_lon(LandmarkLayer.geom)
        with get_postgresql_db() as db:
            rows = db.execute(
                select(lat_expr.label("lat"), lon_expr.label("lon"))
            ).fetchall()
        cells = (RepositoryUtils.lat_lon_to_h3(row.lat, row.lon) for row in rows)
        return dict(Counter(cells))
