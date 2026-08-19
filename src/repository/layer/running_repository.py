from typing import Optional

import pandas as pd
from geoalchemy2 import Geography
from geoalchemy2.functions import (
    ST_Distance,
    ST_DWithin,
    ST_MakePoint,
    ST_SetSRID,
    ST_X,
    ST_Y,
)
from shapely.wkt import loads as wkt_loads
from sqlalchemy import func, insert, select, cast

from src.database.postgresql import get_postgresql_db
from src.entity.layer.running_layer import RunningLayer
from src.repository.utils import RepositoryUtils
from src.entity.network.walk_edge import WalkEdge


class RunningRepository:
    """
    런닝 코스 수집(저장·초기화)과 조회를 담당하는 레포지토리입니다.
    """

    @staticmethod
    def get(lat: float, lon: float, radius_m: int = 2000) -> pd.DataFrame:
        """
        반경 내 러닝 코스 포인트(geom centroid 기준) 전체를 조회합니다.
        course_type을 category로 노출합니다.
        """
        return RepositoryUtils.fetch_nearby_points(
            RunningLayer, lat, lon, radius_m, category_col=RunningLayer.course_type,
        )

    @staticmethod
    def save_all(records: list[dict]):
        """
        코스 데이터를 running_layer 테이블에 벌크 저장합니다. 이미 같은 경위도가 있으면 스킵합니다.
        """
        if not records:
            return
        with get_postgresql_db() as db:
            rows = db.execute(
                select(
                    func.ST_Y(func.ST_Centroid(RunningLayer.geom)).label("lat"),
                    func.ST_X(func.ST_Centroid(RunningLayer.geom)).label("lon"),
                ).where(RunningLayer.geom.isnot(None))
            ).fetchall()
            existing = {(round(float(r.lat), 6), round(float(r.lon), 6)) for r in rows}
            new_records = []
            for r in records:
                pt = wkt_loads(r["geom"].desc)
                centroid = pt.centroid
                if (round(centroid.y, 6), round(centroid.x, 6)) not in existing:
                    new_records.append(r)
            if not new_records:
                return
            db.execute(insert(RunningLayer), new_records)
            db.commit()

    @staticmethod
    def get_running_counts_by_edge(radius_m: int = 50) -> dict[int, int]:
        """
        Edge(walk_edges)로부터 반경 radius_m 이내에 있는 RunningLayer 개수를 Edge별로 집계합니다.
    
        Returns:
            dict[int, int]: {link_id: count} 형태의 딕셔너리.
        """
        edge_geog = cast(WalkEdge.geom, Geography())
        safety_geog = cast(RunningLayer.geom, Geography())
    
        with get_postgresql_db() as db:
            rows = db.execute(
                select(WalkEdge.link_id, func.count(RunningLayer.id))
                # join 연산을 할 때는 기준이 되는 테이블을 명시해야 함.
                # 따라서 select_from() 필요
                .select_from(WalkEdge)
                # edge로부터 Childlayer feature가 radius_m 내에 있으면 join
                .join(RunningLayer, func.ST_DWithin(edge_geog, safety_geog, radius_m))
                .group_by(WalkEdge.link_id)
            ).fetchall()
    
        return {row.link_id: row[1] for row in rows}

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
            {
                "id":                     row.id,
                "name":                   row.name,
                "course_type":            row.course_type,
                "difficulty":             row.difficulty,
                "start_lat":              row.start_lat,
                "start_lon":              row.start_lon,
                "distance_from_origin_m": round(row.distance_from_origin_m, 1),
            }
            for row in rows
        ]

    @staticmethod
    def ensure_generic_geometry() -> None:
        from sqlalchemy import text
        with get_postgresql_db() as db:
            result = db.execute(text(
                "SELECT type FROM geometry_columns "
                "WHERE f_table_name = 'running_layer' AND f_geometry_column = 'geom'"
            )).fetchone()
            if result and result.type != "GEOMETRY":
                db.execute(text(
                    "ALTER TABLE running_layer "
                    "ALTER COLUMN geom TYPE geometry(Geometry, 4326) "
                    "USING geom::geometry(Geometry, 4326)"
                ))
                db.commit()