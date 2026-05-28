import pandas as pd
from sqlalchemy import func, select, cast
from geoalchemy2 import Geography

from src.database.postgresql import get_postgresql_db
from src.entity.layer.safety_layer import SafetyPoint
from src.entity.layer.nature_layer import NaturePoint
from src.entity.layer.landmark_layer import Landmark

_TABLE_ENTITY_MAP: dict[str, type] = {
    "safety_layer": SafetyPoint,
    "poi_layer": NaturePoint,
    "landmark_layer": Landmark,
}


class MapRepository:
    @staticmethod
    def fetch_nearby_points(
        lat: float,
        lon: float,
        table_name: str,
        type_col: str = None,
        type_val: str = None,
        radius_m: int = 2000,
    ) -> pd.DataFrame:
        """
        주어진 좌표 반경 내의 포인트 데이터를 ORM으로 조회합니다.

        Args:
            lat        : 중심 위도.
            lon        : 중심 경도.
            table_name : 조회할 테이블명 (safety_layer / poi_layer / landmark_layer).
            type_col   : 타입 필터링에 사용할 컬럼명 (선택).
            type_val   : 타입 필터링 값 (선택).
            radius_m   : 탐색 반경(미터). 기본값 2,000.

        Returns:
            pd.DataFrame: lat, lon 컬럼을 포함한 데이터프레임.

        Raises:
            ValueError: 지원하지 않는 table_name 또는 존재하지 않는 type_col 지정 시.
        """
        entity = _TABLE_ENTITY_MAP.get(table_name)
        if entity is None:
            raise ValueError(f"지원하지 않는 테이블: {table_name}. 허용값: {list(_TABLE_ENTITY_MAP)}")

        center = cast(func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326), Geography())

        stmt = select(
            func.ST_Y(entity.geom).label("lat"),
            func.ST_X(entity.geom).label("lon"),
        ).where(
            func.ST_DWithin(cast(entity.geom, Geography()), center, radius_m)
        )

        if type_col and type_val:
            col = getattr(entity, type_col, None)
            if col is None:
                raise ValueError(f"'{entity.__tablename__}'에 컬럼 '{type_col}'이 없습니다.")
            stmt = stmt.where(col == type_val)

        try:
            with get_postgresql_db() as db:
                rows = db.execute(stmt).fetchall()
            return pd.DataFrame(rows, columns=["lat", "lon"])
        except Exception as e:
            print(f"DB 포인트 조회 실패 ({table_name}): {e}")
            return pd.DataFrame()
