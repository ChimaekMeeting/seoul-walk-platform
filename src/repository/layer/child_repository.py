from collections import Counter
from typing import List

import pandas as pd
from geoalchemy2 import Geography
from sqlalchemy import cast, func, insert, select

from src.database.postgresql import get_postgresql_db
from src.entity.layer.child_layer import ChildLayer
from src.repository.utils import RepositoryUtils


class ChildRepository:
    @staticmethod
    def get(lat: float, lon: float, radius_m: int = 2000) -> pd.DataFrame:
        """
        반경 내 어린이 시설 포인트 전체를 조회합니다.
        category를 그대로 노출합니다.
        """
        return RepositoryUtils.fetch_nearby_points(
            ChildLayer, lat, lon, radius_m, category_col=ChildLayer.category,
        )

    @staticmethod
    def is_populated() -> bool:
        with get_postgresql_db() as db:
            return db.execute(select(func.count()).select_from(ChildLayer)).scalar() > 0

    @staticmethod
    def save_all(records: List[dict]) -> None:
        """
        어린이 시설 데이터를 child_layer에 벌크 저장합니다.
        """
        with get_postgresql_db() as db:
            db.execute(insert(ChildLayer), records)
            db.commit()

    @staticmethod
    def get_child_h3_counts() -> dict[str, int]:
        """
        H3 셀(resolution 9)별 어린이 시설 개수를 반환합니다.
        walk_edges.child_score 산정에 사용됩니다.
        """
        lat_expr, lon_expr = RepositoryUtils.geom_centroid_lat_lon(ChildLayer.geom)
        with get_postgresql_db() as db:
            rows = db.execute(
                select(lat_expr.label("lat"), lon_expr.label("lon"))
            ).fetchall()
        cells = (RepositoryUtils.lat_lon_to_h3(row.lat, row.lon) for row in rows)
        return dict(Counter(cells))

    @staticmethod
    def get_child_places_near(lat: float, lon: float, radius_m: float) -> list[dict]:
        """
        주어진 좌표 반경 내 어린이 시설 목록을 반환합니다.
        ChildWalkRoute의 런타임 경로 어노테이션에 사용됩니다.
        """
        point = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
        lat_expr = func.ST_Y(ChildLayer.geom)
        lon_expr = func.ST_X(ChildLayer.geom)

        with get_postgresql_db() as db:
            rows = db.execute(
                select(
                    ChildLayer.category,
                    lat_expr.label("lat"),
                    lon_expr.label("lon"),
                ).where(
                    func.ST_DWithin(
                        cast(ChildLayer.geom, Geography),
                        cast(point, Geography),
                        radius_m,
                    )
                )
            ).fetchall()

        return [
            {
                "category": row.category,
                "lat": row.lat,
                "lon": row.lon,
            }
            for row in rows
        ]
