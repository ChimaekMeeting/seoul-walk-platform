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
from sqlalchemy import distinct, func, insert, select, text

from src.database.postgresql import get_postgresql_db, engine
from src.entity.layer.running_layer import RunningLayer, RunningLayerTag
from src.interfaces.schema.running_schema import CourseInfo


class RunningRepository:
    """
    런닝 코스 수집(저장·초기화)과 조회를 담당하는 레포지토리입니다.
    """

    @staticmethod
    def truncate():
        """
        running_layer 테이블의 모든 데이터를 초기화합니다.
        """
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE running_layer RESTART IDENTITY CASCADE"))

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
        H3 셀(resolution 9)별 코스 시작 지점 개수를 반환합니다.
        """
        with get_postgresql_db() as db:
            h3_expr = func.h3_lat_lng_to_cell(RunningLayer.start_geom, 9)
            rows = db.execute(
                select(h3_expr.label("h3_cell"), func.count().label("cnt"))
                .where(RunningLayer.start_geom.isnot(None))
                .group_by(h3_expr)
            ).fetchall()
            return {row.h3_cell: row.cnt for row in rows}

    @staticmethod
    def get_running_layer_near(
        lat: float,
        lon: float,
        radius_m: float = 5_000,
        is_circular: Optional[bool] = None,
        course_types: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
        limit: int = 10,
    ) -> list[CourseInfo]:
        """
        출발점 반경 내 코스를 distance_from_origin_m 오름차순으로 반환합니다.

        Args:
            lat          : 출발점 위도.
            lon          : 출발점 경도.
            radius_m     : 검색 반경(미터). 기본값 5,000.
            is_circular  : True=순환, False=편도, None=전체.
            course_types : 포함할 코스 유형 목록 (OR 조건).
            tags         : 모두 포함해야 할 태그 목록 (AND 조건).
            limit        : 최대 반환 건수. 기본값 10.

        Returns:
            list[CourseInfo]: 코스 정보 목록.
        """
        origin_geog   = ST_SetSRID(ST_MakePoint(lon, lat), 4326).cast(Geography)
        distance_expr = ST_Distance(RunningLayer.start_geom.cast(Geography), origin_geog)

        stmt = (
            select(
                RunningLayer.id,
                RunningLayer.name,
                RunningLayer.course_type,
                RunningLayer.is_circular,
                RunningLayer.distance_m,
                RunningLayer.difficulty,
                RunningLayer.description,
                ST_Y(RunningLayer.start_geom).label("start_lat"),
                ST_X(RunningLayer.start_geom).label("start_lon"),
                distance_expr.label("distance_from_origin_m"),
            )
            .where(RunningLayer.start_geom.isnot(None))
            .where(ST_DWithin(RunningLayer.start_geom.cast(Geography), origin_geog, radius_m))
        )

        if is_circular is not None:
            stmt = stmt.where(RunningLayer.is_circular == is_circular)

        if course_types:
            stmt = stmt.where(RunningLayer.course_type.in_(course_types))

        if tags:
            tag_subquery = (
                select(RunningLayerTag.course_id)
                .where(RunningLayerTag.tag.in_(tags))
                .group_by(RunningLayerTag.course_id)
                .having(func.count(distinct(RunningLayerTag.tag)) == len(tags))
                .scalar_subquery()
            )
            stmt = stmt.where(RunningLayer.id.in_(tag_subquery))

        stmt = stmt.order_by(distance_expr).limit(limit)

        with get_postgresql_db() as db:
            rows = db.execute(stmt).fetchall()
            if not rows:
                return []

            course_ids = [row.id for row in rows]
            tag_rows = db.execute(
                select(RunningLayerTag.course_id, RunningLayerTag.tag).where(
                    RunningLayerTag.course_id.in_(course_ids)
                )
            ).fetchall()

        tags_map: dict[int, list[str]] = {}
        for tr in tag_rows:
            tags_map.setdefault(tr.course_id, []).append(tr.tag)

        return [
            CourseInfo(
                id=row.id,
                name=row.name,
                course_type=row.course_type,
                is_circular=row.is_circular,
                distance_m=row.distance_m,
                difficulty=row.difficulty,
                description=row.description,
                tags=tags_map.get(row.id, []),
                start_lat=row.start_lat,
                start_lon=row.start_lon,
                end_lat=None,
                end_lon=None,
                distance_from_origin_m=round(row.distance_from_origin_m, 1),
            )
            for row in rows
        ]

