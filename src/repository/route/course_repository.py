from typing import Optional

from geoalchemy2 import Geography
from geoalchemy2.functions import (
    ST_AsGeoJSON,
    ST_Distance,
    ST_DWithin,
    ST_MakePoint,
    ST_SetSRID,
    ST_X,
    ST_Y,
)
from sqlalchemy import distinct, func, select

from src.database.postgresql import get_postgresql_db
from src.entity.course import Course, CourseTag


class CourseRepository:
    @staticmethod
    def get_courses_near(
        lat: float,
        lon: float,
        radius_m: float = 5_000,
        is_circular: Optional[bool] = None,
        course_types: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
        limit: int = 10,
    ) -> list[dict]:
        """
        출발점 반경 내 코스를 조회합니다.

        결과는 ``distance_from_origin_m`` 오름차순으로 정렬됩니다.

        Args:
            lat          (float)            : 출발점 위도.
            lon          (float)            : 출발점 경도.
            radius_m     (float)            : 검색 반경 (미터). 기본값 5,000.
            is_circular  (bool, optional)   : ``True``=순환, ``False``=편도, ``None``=전체.
            course_types (list[str], optional): 포함할 코스 유형 목록 (OR 조건).
            tags         (list[str], optional): 모두 포함해야 할 태그 목록 (AND 조건).
            limit        (int)              : 최대 반환 건수. 기본값 10.

        Returns:
            list[dict]: 코스 정보 딕셔너리 리스트.
        """
        origin_geog = ST_SetSRID(ST_MakePoint(lon, lat), 4326).cast(Geography)
        distance_expr = ST_Distance(Course.start_geom.cast(Geography), origin_geog)

        stmt = (
            select(
                Course.id,
                Course.name,
                Course.course_type,
                Course.is_circular,
                Course.distance_m,
                Course.difficulty,
                Course.description,
                ST_Y(Course.start_geom).label("start_lat"),
                ST_X(Course.start_geom).label("start_lon"),
                ST_Y(Course.end_geom).label("end_lat"),
                ST_X(Course.end_geom).label("end_lon"),
                distance_expr.label("distance_from_origin_m"),
            )
            .where(ST_DWithin(Course.start_geom.cast(Geography), origin_geog, radius_m))
        )

        if is_circular is not None:
            stmt = stmt.where(Course.is_circular == is_circular)

        if course_types:
            stmt = stmt.where(Course.course_type.in_(course_types))

        if tags:
            tag_subquery = (
                select(CourseTag.course_id)
                .where(CourseTag.tag.in_(tags))
                .group_by(CourseTag.course_id)
                .having(func.count(distinct(CourseTag.tag)) == len(tags))
                .scalar_subquery()
            )
            stmt = stmt.where(Course.id.in_(tag_subquery))

        stmt = stmt.order_by(distance_expr).limit(limit)

        with get_postgresql_db() as db:
            rows = db.execute(stmt).fetchall()

            if not rows:
                return []

            course_ids = [row.id for row in rows]
            tag_rows = db.execute(
                select(CourseTag.course_id, CourseTag.tag).where(
                    CourseTag.course_id.in_(course_ids)
                )
            ).fetchall()

        tags_map: dict[int, list[str]] = {}
        for tr in tag_rows:
            tags_map.setdefault(tr.course_id, []).append(tr.tag)

        return [
            {
                "id":                     row.id,
                "name":                   row.name,
                "course_type":            row.course_type,
                "is_circular":            row.is_circular,
                "distance_m":             row.distance_m,
                "difficulty":             row.difficulty,
                "description":            row.description,
                "tags":                   tags_map.get(row.id, []),
                "start_lat":              row.start_lat,
                "start_lon":              row.start_lon,
                "end_lat":                row.end_lat,
                "end_lon":                row.end_lon,
                "distance_from_origin_m": round(row.distance_from_origin_m, 1),
            }
            for row in rows
        ]

    @staticmethod
    def get_course_by_id(course_id: int) -> Optional[dict]:
        """
        단일 코스를 상세 조회합니다.

        Args:
            course_id (int): 조회할 코스 PK.

        Returns:
            dict | None: 코스가 존재하면 딕셔너리, 없으면 ``None``.
        """
        with get_postgresql_db() as db:
            row = db.execute(
                select(
                    Course.id,
                    Course.name,
                    Course.course_type,
                    Course.is_circular,
                    Course.distance_m,
                    Course.difficulty,
                    Course.description,
                    Course.source,
                    ST_Y(Course.start_geom).label("start_lat"),
                    ST_X(Course.start_geom).label("start_lon"),
                    ST_Y(Course.end_geom).label("end_lat"),
                    ST_X(Course.end_geom).label("end_lon"),
                    ST_AsGeoJSON(Course.geom).label("geojson"),
                ).where(Course.id == course_id)
            ).fetchone()

            if not row:
                return None

            tag_rows = db.execute(
                select(CourseTag.tag).where(CourseTag.course_id == course_id)
            ).fetchall()

        return {
            "id":          row.id,
            "name":        row.name,
            "course_type": row.course_type,
            "is_circular": row.is_circular,
            "distance_m":  row.distance_m,
            "difficulty":  row.difficulty,
            "description": row.description,
            "source":      row.source,
            "tags":        [tr.tag for tr in tag_rows],
            "start_lat":   row.start_lat,
            "start_lon":   row.start_lon,
            "end_lat":     row.end_lat,
            "end_lon":     row.end_lon,
            "geojson":     row.geojson,
        }
