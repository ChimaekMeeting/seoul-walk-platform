import geopandas as gpd
import pandas as pd
from geoalchemy2.elements import WKTElement
from sqlalchemy import exists, select

from src.database.postgresql import engine, get_postgresql_db
from src.entity.raw.csv_raw import CsvRaw
from src.repository.utils import serialize


class CsvRawRepository:
    @staticmethod
    def exists(query_key: str) -> bool:
        with get_postgresql_db() as db:
            return db.execute(
                select(exists().where(CsvRaw.query_key == query_key))
            ).scalar()

    @staticmethod
    def save(
        df: pd.DataFrame,
        query_key: str,
        lat_col: str,
        lon_col: str,
        name_col: str | None = None,
    ) -> None:
        records = []
        for _, row in df.iterrows():
            try:
                lat = float(row[lat_col])
                lon = float(row[lon_col])
            except (KeyError, ValueError, TypeError):
                continue

            exclude = {lat_col, lon_col, name_col} - {None}
            props = {
                col: serialize(row[col])
                for col in row.index
                if col not in exclude
            }

            records.append(CsvRaw(
                query_key=query_key,
                name=str(row[name_col]) if name_col and row.get(name_col) is not None else None,
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
                "SELECT id AS csv_raw_id, name, properties, geom FROM csv_raw WHERE query_key = %(key)s",
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
