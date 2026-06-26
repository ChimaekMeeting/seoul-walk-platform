import geopandas as gpd
from sqlalchemy import text

from src.database.postgresql import get_postgresql_db, engine


class WaterPolygonRepository:
    @staticmethod
    def save_geodataframe(gdf: gpd.GeoDataFrame) -> None:
        if gdf.empty:
            return
        with get_postgresql_db() as db:
            rows = db.execute(text(
                "SELECT ST_Y(ST_Centroid(geom)) as lat, ST_X(ST_Centroid(geom)) as lon "
                "FROM seoul_water_polygons"
            )).fetchall()
        existing = {(round(float(r.lat), 6), round(float(r.lon), 6)) for r in rows}
        centroids = gdf.geometry.centroid
        mask = [(round(c.y, 6), round(c.x, 6)) not in existing for c in centroids]
        gdf = gdf[mask]
        if gdf.empty:
            return
        gdf.to_postgis("seoul_water_polygons", engine, if_exists="append", index=False)

    @staticmethod
    def create_spatial_index() -> None:
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_seoul_water_geom "
                "ON seoul_water_polygons USING GIST(geom)"
            ))
