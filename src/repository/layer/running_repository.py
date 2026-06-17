from typing import Optional

from geoalchemy2 import Geography
from geoalchemy2.functions import (
    ST_Distance,
    ST_DWithin,
    ST_MakePoint,
    ST_SetSRID,
    ST_X,
    ST_Y,
)
from sqlalchemy import func, insert, select

from src.database.postgresql import get_postgresql_db
from src.entity.layer.running_layer import RunningLayer
from src.repository.utils import RepositoryUtils


class RunningRepository:
    """
    런닝 코스 수집(저장·초기화)과 조회를 담당하는 레포지토리입니다.
    """

    @staticmethod
    def save_all(records: list[dict]):
        """
        코스 데이터를 running_layer 테이블에 벌크 저장합니다.
        """
        with get_postgresql_db() as db:
            db.execute(insert(RunningLayer), records)
            db.commit()

    @staticmethod
    def get_running_h3_counts() -> dict[str, int]:
        """
        H3 셀(resolution 9)별 코스 지점 개수를 반환합니다.
        """
        from collections import Counter
        lat_expr, lon_expr = RepositoryUtils.geom_centroid_lat_lon(RunningLayer.geom)
        with get_postgresql_db() as db:
            rows = db.execute(
                select(lat_expr.label("lat"), lon_expr.label("lon"))
                .where(RunningLayer.geom.isnot(None))
            ).fetchall()
        cells = (RepositoryUtils.lat_lon_to_h3(row.lat, row.lon) for row in rows)
        return dict(Counter(cells))

    @staticmethod
    def get_running_layer_near(
        lat: float,
        lon: float,
        radius_m: float = 5_000,
        course_types: Optional[list[str]] = None,
        limit: int = 10,
    ) -> list[dict]:
        """
        출발점 반경 내 코스를 distance_from_origin_m 오름차순으로 반환합니다.

        Args:
            lat          : 출발점 위도.
            lon          : 출발점 경도.
            radius_m     : 검색 반경(미터). 기본값 5,000.
            course_types : 포함할 코스 유형 목록 (OR 조건).
            limit        : 최대 반환 건수. 기본값 10.

        Returns:
            list[dict]: 코스 정보 목록.
        """
        origin_geog   = ST_SetSRID(ST_MakePoint(lon, lat), 4326).cast(Geography)
        distance_expr = ST_Distance(RunningLayer.geom.cast(Geography), origin_geog)

        stmt = (
            select(
                RunningLayer.id,
                RunningLayer.name,
                RunningLayer.course_type,
                RunningLayer.difficulty,
                ST_Y(func.ST_Centroid(RunningLayer.geom)).label("start_lat"),
                ST_X(func.ST_Centroid(RunningLayer.geom)).label("start_lon"),
                distance_expr.label("distance_from_origin_m"),
            )
            .where(RunningLayer.geom.isnot(None))
            .where(ST_DWithin(RunningLayer.geom.cast(Geography), origin_geog, radius_m))
        )

        if course_types:
            stmt = stmt.where(RunningLayer.course_type.in_(course_types))

        stmt = stmt.order_by(distance_expr).limit(limit)

        with get_postgresql_db() as db:
            rows = db.execute(stmt).fetchall()
            if not rows:
                return []

        return [
            CourseInfo(
                id=row.id,
                name=row.name,
                course_type=row.course_type,
                difficulty=row.difficulty,
                start_lat=row.start_lat,
                start_lon=row.start_lon,
                distance_from_origin_m=round(row.distance_from_origin_m, 1),
            )
            for row in rows
        ]
