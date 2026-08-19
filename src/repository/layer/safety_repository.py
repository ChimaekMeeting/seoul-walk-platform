from typing import List

import pandas as pd
from shapely.wkt import loads as wkt_loads
from sqlalchemy import delete, func, insert, select, cast
from geoalchemy2 import Geography

from src.database.postgresql import get_postgresql_db
from src.entity.layer.safety_layer import SafetyLayer
from src.repository.utils import RepositoryUtils
from src.entity.network.walk_edge import WalkEdge


class SafetyRepository:
    @staticmethod
    def get(lat: float, lon: float, radius_m: int = 2000) -> pd.DataFrame:
        """
        반경 내 안전 시설물 포인트 전체를 조회합니다.
        safety_type(예: cctv, streetlight)을 category로 노출합니다.
        """
        return RepositoryUtils.fetch_nearby_points(
            SafetyLayer, lat, lon, radius_m, category_col=SafetyLayer.safety_type,
        )

    @staticmethod
    def save_all(records: List[dict]):
        """
        안전 시설물 데이터를 safety_layer에 벌크 저장합니다. 이미 같은 경위도가 있으면 스킵합니다.
        """
        if not records:
            return
        with get_postgresql_db() as db:
            rows = db.execute(
                select(func.ST_Y(SafetyLayer.geom).label("lat"), func.ST_X(SafetyLayer.geom).label("lon"))
            ).fetchall()
            existing = {(round(float(r.lat), 6), round(float(r.lon), 6)) for r in rows}
            new_records = []
            for r in records:
                pt = wkt_loads(r["geom"].desc)
                if (round(pt.y, 6), round(pt.x, 6)) not in existing:
                    new_records.append(r)
            if not new_records:
                return
            db.execute(insert(SafetyLayer), new_records)
            db.commit()

    @staticmethod
    def replace_types(records: List[dict], safety_types: set[str]) -> None:
        """지정한 안전 유형만 현재 수집 결과로 원자적으로 교체합니다."""
        with get_postgresql_db() as db:
            db.execute(
                delete(SafetyLayer).where(
                    SafetyLayer.safety_type.in_(safety_types)
                )
            )
            if records:
                db.execute(insert(SafetyLayer), records)
            db.commit()

    @staticmethod
    def get_safety_counts_by_edge(radius_m: int = 50) -> dict[int, int]:
        """
        Edge(walk_edges)로부터 반경 radius_m 이내에 있는 SafetyLayer 개수를 Edge별로 집계합니다.

        Returns:
            dict[int, int]: {link_id: count} 형태의 딕셔너리.
        """
        edge_geog = cast(WalkEdge.geom, Geography())
        safety_geog = cast(SafetyLayer.geom, Geography())

        with get_postgresql_db() as db:
            rows = db.execute(
                select(WalkEdge.link_id, func.count(SafetyLayer.id))
                # join 연산을 할 때는 기준이 되는 테이블을 명시해야 함.
                # 따라서 select_from() 필요
                .select_from(WalkEdge)
                # edge로부터 safetylayer feature가 radius_m 내에 있으면 join
                .join(SafetyLayer, func.ST_DWithin(edge_geog, safety_geog, radius_m))
                .group_by(WalkEdge.link_id)
            ).fetchall()

        return {row.link_id: row[1] for row in rows}
