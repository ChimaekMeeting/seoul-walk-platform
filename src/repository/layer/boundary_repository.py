import geopandas as gpd
from sqlalchemy import func, select, text

from src.database.postgresql import get_postgresql_db, engine
from src.entity.layer.seoul_administrative_boundary import SeoulAdministrativeBoundary


class BoundaryRepository:
    @staticmethod
    def is_populated() -> bool:
        with get_postgresql_db() as db:
            return db.execute(
                select(func.count()).select_from(SeoulAdministrativeBoundary)
            ).scalar() > 0

    @staticmethod
    def save_geodataframe(gdf: gpd.GeoDataFrame) -> None:
        gdf.to_postgis("seoul_administrative_boundary", engine, if_exists="append", index=False)

    @staticmethod
    def create_spatial_index() -> None:
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_seoul_boundary_geom "
                "ON seoul_administrative_boundary USING GIST(geom)"
            ))
