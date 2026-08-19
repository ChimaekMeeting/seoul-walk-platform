from typing import List

import pandas as pd
from geoalchemy2 import Geography
from shapely.wkt import loads as wkt_loads
from sqlalchemy import cast, func, select, insert

from src.database.postgresql import get_postgresql_db
from src.entity.layer.landmark_layer import LandmarkLayer
from src.entity.network.walk_edge import WalkEdge
from src.repository.utils import RepositoryUtils


class LandmarkRepository:
    @staticmethod
    def get(lat: float, lon: float, radius_m: int = 2000) -> pd.DataFrame:
        """
        반경 내 랜드마크 포인트를 조회합니다. (타입 필터 없음)
        """
        return RepositoryUtils.fetch_nearby_points(LandmarkLayer, lat, lon, radius_m)

    @staticmethod
    def save_all(landmarks: List[dict]):
        """
        랜드마크 데이터를 landmark_layer에 벌크 저장합니다. 이미 같은 경위도가 있으면 스킵합니다.
        """
        if not landmarks:
            return
        with get_postgresql_db() as db:
            rows = db.execute(
                select(func.ST_Y(LandmarkLayer.geom).label("lat"), func.ST_X(LandmarkLayer.geom).label("lon"))
            ).fetchall()
            existing = {(round(float(r.lat), 6), round(float(r.lon), 6)) for r in rows}
            new_records = []
            for r in landmarks:
                pt = wkt_loads(r["geom"].desc)
                if (round(pt.y, 6), round(pt.x, 6)) not in existing:
                    new_records.append(r)
            if not new_records:
                return
            db.execute(insert(LandmarkLayer), new_records)
            db.commit()

    @staticmethod
    def get_landmark_counts_by_edge(radius_m: int = 50) -> dict[int, int]:
        """
        Edge(walk_edges)로부터 반경 radius_m 이내에 있는 LandmarkLayer 개수를 Edge별로 집계합니다.

        Returns:
            dict[int, int]: {link_id: count} 형태의 딕셔너리.
        """
        edge_geog = cast(WalkEdge.geom, Geography())
        landmark_geog = cast(LandmarkLayer.geom, Geography())

        with get_postgresql_db() as db:
            rows = db.execute(
                select(WalkEdge.link_id, func.count(LandmarkLayer.id))
                # join 연산을 할 때는 기준이 되는 테이블을 명시해야 함.
                # 따라서 select_from() 필요
                .select_from(WalkEdge)
                # edge로부터 LandmarkLayer feature가 radius_m 내에 있으면 join
                .join(LandmarkLayer, func.ST_DWithin(edge_geog, landmark_geog, radius_m))
                .group_by(WalkEdge.link_id)
            ).fetchall()

        return {row.link_id: row[1] for row in rows}
