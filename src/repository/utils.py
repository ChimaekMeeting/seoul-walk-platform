import math

import numpy as np
import pandas as pd
from sqlalchemy import func, select, cast
from geoalchemy2 import Geography

from src.database.postgresql import get_postgresql_db
import logging
logger = logging.getLogger(__name__)


class RepositoryUtils:
    @staticmethod
    def geom_centroid_lat_lon(geom):
        centroid = func.ST_Centroid(geom)
        return func.ST_Y(centroid), func.ST_X(centroid)

    @staticmethod
    def fetch_nearby_points(
        entity,
        lat: float,
        lon: float,
        radius_m: int = 2000,
        category_col=None,
    ) -> pd.DataFrame:
        """
        주어진 엔티티 테이블에서 반경 내 포인트(폴리곤은 centroid 기준) 전체를 조회합니다.

        Args:
            entity       : 조회 대상 SQLAlchemy 엔티티 클래스.
            lat          : 중심 위도.
            lon          : 중심 경도.
            radius_m     : 탐색 반경(미터). 기본값 2,000.
            category_col : 카테고리로 노출할 판별 컬럼 (선택). 지정 시 "category" 키로 반환.

        Returns:
            pd.DataFrame: lat, lon (+ category) 컬럼을 포함한 데이터프레임. 실패 시 빈 데이터프레임.
        """
        center = cast(func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326), Geography())
        lat_expr, lon_expr = RepositoryUtils.geom_centroid_lat_lon(entity.geom)

        columns = [lat_expr.label("lat"), lon_expr.label("lon")]
        if category_col is not None:
            columns.append(category_col.label("category"))

        stmt = select(*columns).where(
            func.ST_DWithin(cast(entity.geom, Geography()), center, radius_m)
        )

        df_columns = [c.name for c in columns]
        try:
            with get_postgresql_db() as db:
                rows = db.execute(stmt).fetchall()
            return pd.DataFrame(rows, columns=df_columns)
        except Exception as e:
            logger.info(f"DB 포인트 조회 실패 ({entity.__tablename__}): {e}")
            return pd.DataFrame()


def serialize(val):
    """ORM insert 전 JSONB 직렬화 가능한 형태로 변환합니다."""
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    if isinstance(val, np.integer):
        return int(val)
    if isinstance(val, np.floating):
        return None if np.isnan(val) else float(val)
    if isinstance(val, (str, int, float, bool)):
        return val
    if isinstance(val, list):
        return [serialize(v) for v in val]
    return str(val)
