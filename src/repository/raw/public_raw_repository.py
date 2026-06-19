import geopandas as gpd
import pandas as pd
from geoalchemy2.elements import WKTElement
from sqlalchemy import exists, select

from src.database.postgresql import engine, get_postgresql_db
from src.entity.raw.public_raw import PublicRaw
from src.repository.utils import serialize


class PublicRawRepository:
    @staticmethod
    def exists(query_key: str) -> bool:
        with get_postgresql_db() as db:
            return db.execute(
                select(exists().where(PublicRaw.query_key == query_key))
            ).scalar()

    @staticmethod
    def save(items: list[dict], query_key: str) -> None:
        exclude = {"lat", "lon", "name"}
        records = []
        for item in items:
            try:
                lat = float(item["lat"])
                lon = float(item["lon"])
            except (KeyError, ValueError, TypeError):
                continue

            props = {k: serialize(v) for k, v in item.items() if k not in exclude}

            records.append(PublicRaw(
                query_key=query_key,
                name=item.get("name"),
                geom=WKTElement(f"POINT({lon} {lat})", srid=4326),
                properties=props or None,
            ))

        with get_postgresql_db() as db:
            db.add_all(records)
            db.commit()

    @staticmethod
    def get(query_key: str) -> gpd.GeoDataFrame:
        with engine.connect() as conn:
            gdf = gpd.read_postgis(
                "SELECT id AS public_raw_id, name, properties, geom FROM public_raw WHERE query_key = %(key)s",
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
