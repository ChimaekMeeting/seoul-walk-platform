import geopandas as gpd
from sqlalchemy import func, select, text

from src.database.postgresql import get_postgresql_db, engine
from src.entity.layer.nature_layer import NatureLayer


class NatureRepository:
    @staticmethod
    def truncate():
        """
        nature_layer 테이블의 모든 데이터를 초기화합니다.
        """
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE nature_layer RESTART IDENTITY CASCADE"))

    @staticmethod
    def save_geodataframe(gdf: gpd.GeoDataFrame) -> None:
        """
        OSM 녹지 폴리곤 GeoDataFrame을 nature_layer 테이블에 저장합니다.
        """
        gdf.to_postgis("nature_layer", engine, if_exists="append", index=False)

    @staticmethod
    def get_nature_h3_counts() -> dict[str, int]:
        """
        H3 셀(resolution 9)별 녹지 폴리곤 개수를 반환합니다.
        폴리곤의 중심점(centroid)을 기준으로 H3 셀을 계산합니다.
        """
        with get_postgresql_db() as db:
            h3_expr = func.h3_lat_lng_to_cell(func.ST_Centroid(NatureLayer.geom), 9)
            rows = db.execute(
                select(h3_expr.label("h3_cell"), func.count().label("cnt"))
                .group_by(h3_expr)
            ).fetchall()
            return {row.h3_cell: row.cnt for row in rows}

