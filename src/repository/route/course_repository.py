"""
런닝/다이어트 코스 레포지토리.

PostGIS ``ST_DWithin``을 활용해 출발점 반경 내 코스를 조회합니다.

공개 함수
---------
- ``get_courses_near``  : 반경 내 코스 목록 조회 (필터·태그 지원)
- ``get_course_by_id``  : 단일 코스 상세 조회
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.database.postgresql import get_postgresql_db
from src.entity.course import Course, CourseTag


# ──────────────────────────────────────────────────────────────
# 조회 함수
# ──────────────────────────────────────────────────────────────

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

    내부에서 ``get_postgresql_db()``로 DB 연결을 자체 관리하므로
    외부에서 세션을 주입할 필요가 없습니다.

    결과는 ``distance_from_origin_m`` 오름차순으로 정렬됩니다.
    (``results[0]``이 출발점에 가장 가까운 코스)

    Args:
        lat          (float)            : 출발점 위도.
        lon          (float)            : 출발점 경도.
        radius_m     (float)            : 검색 반경 (미터). 기본값 5,000.
        is_circular  (bool, optional)   : ``True``=순환, ``False``=편도, ``None``=전체.
        course_types (list[str], optional): 포함할 코스 유형 목록 (OR 조건).
                                           예: ``["river", "park", "bike_track"]``
        tags         (list[str], optional): 모두 포함해야 할 태그 목록 (**AND 조건**).
                                           예: ``["런닝", "야간가능"]`` → 두 태그 모두 있는 코스만.
        limit        (int)              : 최대 반환 건수. 기본값 10.

    Returns:
        list[dict]: 코스 정보 딕셔너리 리스트. 코스가 없으면 빈 리스트.
        각 딕셔너리의 구조::

            {
                "id"                    : int,
                "name"                  : str,
                "course_type"           : str,   # "river" | "park" | "bike_track" | "trail"
                "is_circular"           : bool,
                "distance_m"            : float | None,
                "difficulty"            : str | None,  # "easy" | "medium" | "hard"
                "description"           : str | None,
                "tags"                  : list[str],
                "start_lat"             : float,
                "start_lon"             : float,
                "end_lat"               : float | None,
                "end_lon"               : float | None,
                "distance_from_origin_m": float,  # 출발점까지의 거리 (미터)
            }
    """
    with get_postgresql_db() as db:
        # ── 동적 WHERE 절 구성 ──────────────────────────────
        conditions = [
            "ST_DWithin(c.start_geom::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :radius)"
        ]
        params: dict = {"lat": lat, "lon": lon, "radius": radius_m, "limit": limit}

        if is_circular is not None:
            conditions.append("c.is_circular = :is_circular")
            params["is_circular"] = is_circular

        if course_types:
            placeholders = ", ".join(f":ct{i}" for i in range(len(course_types)))
            conditions.append(f"c.course_type IN ({placeholders})")
            for i, ct in enumerate(course_types):
                params[f"ct{i}"] = ct

        where_clause = " AND ".join(conditions)

        # ── 태그 필터 (서브쿼리) ────────────────────────────
        tag_subquery = ""
        if tags:
            tag_placeholders = ", ".join(f":tag{i}" for i in range(len(tags)))
            tag_subquery = f"""
                AND c.id IN (
                    SELECT course_id FROM course_tags
                    WHERE tag IN ({tag_placeholders})
                    GROUP BY course_id
                    HAVING COUNT(DISTINCT tag) = :tag_count
                )
            """
            for i, tag in enumerate(tags):
                params[f"tag{i}"] = tag
            params["tag_count"] = len(tags)

        sql = text(f"""
            SELECT
                c.id,
                c.name,
                c.course_type,
                c.is_circular,
                c.distance_m,
                c.difficulty,
                c.description,
                ST_Y(c.start_geom::geometry)  AS start_lat,
                ST_X(c.start_geom::geometry)  AS start_lon,
                ST_Y(c.end_geom::geometry)    AS end_lat,
                ST_X(c.end_geom::geometry)    AS end_lon,
                ST_Distance(
                    c.start_geom::geography,
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
                ) AS distance_from_origin_m
            FROM courses c
            WHERE {where_clause}
            {tag_subquery}
            ORDER BY distance_from_origin_m ASC
            LIMIT :limit
        """)

        rows = db.execute(sql, params).fetchall()

        if not rows:
            return []

        # ── 태그 일괄 조회 ──────────────────────────────────
        course_ids = [row.id for row in rows]
        id_placeholders = ", ".join(f":cid{i}" for i in range(len(course_ids)))
        tag_rows = db.execute(
            text(f"SELECT course_id, tag FROM course_tags WHERE course_id IN ({id_placeholders})"),
            {f"cid{i}": cid for i, cid in enumerate(course_ids)},
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


def get_course_by_id(course_id: int) -> Optional[dict]:
    """
    단일 코스를 상세 조회합니다.

    Args:
        course_id (int): 조회할 코스 PK.

    Returns:
        dict | None: 코스가 존재하면 딕셔너리, 없으면 ``None``.
        딕셔너리 구조::

            {
                "id"          : int,
                "name"        : str,
                "course_type" : str,
                "is_circular" : bool,
                "distance_m"  : float | None,
                "difficulty"  : str | None,
                "description" : str | None,
                "source"      : str | None,
                "tags"        : list[str],
                "start_lat"   : float | None,
                "start_lon"   : float | None,
                "end_lat"     : float | None,
                "end_lon"     : float | None,
                "geojson"     : str | None,  # GeoJSON 문자열 (경로 전체 선형)
            }
    """
    with get_postgresql_db() as db:
        row = db.execute(
            text("""
                SELECT
                    c.id, c.name, c.course_type, c.is_circular,
                    c.distance_m, c.difficulty, c.description, c.source,
                    ST_Y(c.start_geom::geometry) AS start_lat,
                    ST_X(c.start_geom::geometry) AS start_lon,
                    ST_Y(c.end_geom::geometry)   AS end_lat,
                    ST_X(c.end_geom::geometry)   AS end_lon,
                    ST_AsGeoJSON(c.geom)          AS geojson
                FROM courses c
                WHERE c.id = :course_id
            """),
            {"course_id": course_id},
        ).fetchone()

        if not row:
            return None

        tag_rows = db.execute(
            text("SELECT tag FROM course_tags WHERE course_id = :cid"),
            {"cid": course_id},
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
