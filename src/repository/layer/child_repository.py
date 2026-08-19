from typing import List

import pandas as pd
from geoalchemy2 import Geography
from shapely.wkt import loads as wkt_loads
from sqlalchemy import cast, delete, func, insert, select, text

from src.database.postgresql import engine, get_postgresql_db
from src.entity.layer.child_layer import ChildLayer
from src.repository.utils import RepositoryUtils
from src.entity.network.walk_edge import WalkEdge


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
    def save_all(records: List[dict]) -> None:
        """
        어린이 시설 데이터를 child_layer에 벌크 저장합니다. 이미 같은 경위도가 있으면 스킵합니다.
        """
        if not records:
            return
        with get_postgresql_db() as db:
            rows = db.execute(
                select(func.ST_Y(ChildLayer.geom).label("lat"), func.ST_X(ChildLayer.geom).label("lon"))
            ).fetchall()
            existing = {(round(float(r.lat), 6), round(float(r.lon), 6)) for r in rows}
            new_records = []
            for r in records:
                pt = wkt_loads(r["geom"].desc)
                if (round(pt.y, 6), round(pt.x, 6)) not in existing:
                    new_records.append(r)
            if not new_records:
                return
            db.execute(insert(ChildLayer), new_records)
            db.commit()

    @staticmethod
    def replace_categories(
        records: List[dict],
        categories: set[str],
    ) -> None:
        """지정한 어린이 데이터 유형만 현재 수집 결과로 교체합니다."""
        with get_postgresql_db() as db:
            db.execute(
                delete(ChildLayer).where(
                    ChildLayer.category.in_(categories)
                )
            )
            if records:
                db.execute(insert(ChildLayer), records)
            db.commit()

    @staticmethod
    def get_child_counts_by_edge(radius_m: int = 50) -> dict[int, int]:
        """
        Edge(walk_edges)로부터 반경 radius_m 이내에 있는 ChildLayer 개수를 Edge별로 집계합니다.

        Returns:
            dict[int, int]: {link_id: count} 형태의 딕셔너리.
        """
        edge_geog = cast(WalkEdge.geom, Geography())
        safety_geog = cast(ChildLayer.geom, Geography())

        with get_postgresql_db() as db:
            rows = db.execute(
                select(WalkEdge.link_id, func.count(ChildLayer.id))
                # join 연산을 할 때는 기준이 되는 테이블을 명시해야 함.
                # 따라서 select_from() 필요
                .select_from(WalkEdge)
                # edge로부터 Childlayer feature가 radius_m 내에 있으면 join
                .join(ChildLayer, func.ST_DWithin(edge_geog, safety_geog, radius_m))
                .group_by(WalkEdge.link_id)
            ).fetchall()

        return {row.link_id: row[1] for row in rows}

    @staticmethod
    def update_nearest_school_zone_edges(max_distance_m: float = 50.0) -> int:
        """
        어린이보호구역 Point마다 50m 안의 최근접 보행 Edge 하나를 차량 주의
        후보로 표시합니다.

        Point 중심만으로 보호구역 전체 도로 범위를 확정할 수 없으므로 이 필드는
        자동 차단이 아니라 주의·감점 입력으로만 사용합니다.
        """
        reset = text(
            """
            UPDATE walk_edges
            SET is_school_zone = false,
                is_vehicle_caution = false
            """
        )
        update = text(
            """
            WITH nearest_edges AS (
                SELECT DISTINCT ON (child.id)
                    child.id AS child_id,
                    edge.link_id
                FROM child_layer AS child
                JOIN walk_edges AS edge
                  ON edge.is_walkable = true
                 AND ST_DWithin(
                        child.geom::geography,
                        edge.geom::geography,
                        :max_distance_m
                     )
                WHERE child.category = '어린이보호구역'
                ORDER BY
                    child.id,
                    ST_Distance(
                        child.geom::geography,
                        edge.geom::geography
                    ),
                    edge.link_id
            )
            UPDATE walk_edges AS edge
            SET is_school_zone = true,
                is_vehicle_caution = true
            FROM (
                SELECT DISTINCT link_id
                FROM nearest_edges
            ) AS matched
            WHERE edge.link_id = matched.link_id
            """
        )
        with engine.begin() as connection:
            connection.execute(reset)
            result = connection.execute(
                update,
                {"max_distance_m": max_distance_m},
            )
        return result.rowcount

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
