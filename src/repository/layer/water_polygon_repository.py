import geopandas as gpd
from sqlalchemy import func, select, text

from src.database.postgresql import get_postgresql_db, engine
from src.entity.layer.seoul_water_polygon import SeoulWaterPolygon


class WaterPolygonRepository:
    @staticmethod
    def is_populated() -> bool:
        with get_postgresql_db() as db:
            return db.execute(
                select(func.count()).select_from(SeoulWaterPolygon)
            ).scalar() > 0

    @staticmethod
    def save_geodataframe(gdf: gpd.GeoDataFrame) -> None:
        gdf.to_postgis("seoul_water_polygons", engine, if_exists="append", index=False)

    @staticmethod
    def create_spatial_index() -> None:
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_seoul_water_geom "
                "ON seoul_water_polygons USING GIST(geom)"
            ))
