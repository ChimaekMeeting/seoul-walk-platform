import geopandas as gpd
import pandas as pd
from geoalchemy2.elements import WKTElement
from sqlalchemy import exists, select

from src.database.postgresql import engine, get_postgresql_db
from src.entity.raw.osm_raw import OsmRaw
from src.repository.utils import serialize


class OsmRawRepository:
    @staticmethod
    def exists(query_key: str) -> bool:
        with get_postgresql_db() as db:
            return db.execute(
                select(exists().where(OsmRaw.query_key == query_key))
            ).scalar()

    @staticmethod
    def save(gdf: gpd.GeoDataFrame, query_key: str) -> None:
        exclude = {gdf.geometry.name}
        records = []

        for _, row in gdf.iterrows():
            try:
                wkt = row[exclude].wkt
            except Exception:
                continue

            props = {
                col: serialize(row[col])
                for col in row.index
                if col not in exclude
            }

            records.append(OsmRaw(
                query_key=query_key,
                geom=WKTElement(wkt, srid=4326),
                properties=props or None,
            ))

        with get_postgresql_db() as db:
            db.add_all(records)
            db.commit()

    @staticmethod
    def get(query_key: str) -> gpd.GeoDataFrame:
        with engine.connect() as conn:
            gdf = gpd.read_postgis(
                "SELECT id AS osm_raw_id, properties, geom FROM osm_raw WHERE query_key = %(key)s",
                conn,
                geom_col="geom",
                params={"key": query_key},
                crs="EPSG:4326",
            )

        if gdf.empty:
            return gdf

        props_df = pd.json_normalize(gdf["properties"].tolist())
        props_df.index = gdf.index
        return pd.concat([gdf.drop(columns=["properties"]), props_df], axis=1)
