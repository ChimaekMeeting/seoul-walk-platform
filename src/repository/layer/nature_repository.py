from collections import Counter

import geopandas as gpd
import pandas as pd
from sqlalchemy import func, select

from src.database.postgresql import get_postgresql_db, engine
from src.entity.layer.nature_layer import NatureLayer
from src.repository.utils import RepositoryUtils


class NatureRepository:
    @staticmethod
    def get(lat: float, lon: float, radius_m: int = 2000) -> pd.DataFrame:
        """
        반경 내 녹지 포인트(폴리곤은 centroid 기준) 전체를 조회합니다.
        green_type을 category로 노출합니다.
        """
        return RepositoryUtils.fetch_nearby_points(
            NatureLayer, lat, lon, radius_m, category_col=NatureLayer.green_type,
        )

    @staticmethod
    def save_geodataframe(gdf: gpd.GeoDataFrame) -> None:
        """
        OSM 녹지 폴리곤 GeoDataFrame을 nature_layer 테이블에 저장합니다. 중심점 경위도가 같으면 스킵합니다.
        """
        if gdf.empty:
            return
        with get_postgresql_db() as db:
            rows = db.execute(
                select(
                    func.ST_Y(func.ST_Centroid(NatureLayer.geom)).label("lat"),
                    func.ST_X(func.ST_Centroid(NatureLayer.geom)).label("lon"),
                )
            ).fetchall()
        existing = {(round(float(r.lat), 6), round(float(r.lon), 6)) for r in rows}
        centroids = gdf.geometry.centroid
        mask = [(round(c.y, 6), round(c.x, 6)) not in existing for c in centroids]
        gdf = gdf[mask]
        if gdf.empty:
            return
        gdf.to_postgis("nature_layer", engine, if_exists="append", index=False)

    @staticmethod
    def get_nature_h3_counts() -> dict[str, int]:
        """
        H3 셀(resolution 9)별 녹지 폴리곤 개수를 반환합니다.
        폴리곤의 중심점(centroid)을 기준으로 H3 셀을 계산합니다.
        """
        lat_expr, lon_expr = RepositoryUtils.geom_centroid_lat_lon(NatureLayer.geom)
        with get_postgresql_db() as db:
            rows = db.execute(
                select(lat_expr.label("lat"), lon_expr.label("lon"))
            ).fetchall()
        cells = (RepositoryUtils.lat_lon_to_h3(row.lat, row.lon) for row in rows)
        return dict(Counter(cells))
