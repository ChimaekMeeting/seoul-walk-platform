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
    def save(df: pd.DataFrame, query_key: str) -> None:
        use_linestring = "end_lat" in df.columns
        # lat/lon/end coords와 name은 전용 컬럼으로 저장하므로 properties에서 제외
        # address는 properties에 "address" 키로 유지
        geom_cols = {"lat", "lon", "end_lat", "end_lon"} if use_linestring else {"lat", "lon"}
        exclude = geom_cols | {"name"}
        records = []

        for _, row in df.iterrows():
            try:
                lat = float(row["lat"])
                lon = float(row["lon"])
            except (KeyError, ValueError, TypeError):
                continue

            if use_linestring:
                try:
                    end_lat = float(row["end_lat"])
                    end_lon = float(row["end_lon"])
                except (KeyError, ValueError, TypeError):
                    continue
                wkt = f"LINESTRING({lon} {lat}, {end_lon} {end_lat})"
            else:
                wkt = f"POINT({lon} {lat})"

            props = {
                col: serialize(row[col])
                for col in row.index
                if col not in exclude
            }

            name_val = row.get("name")
            records.append(CsvRaw(
                query_key=query_key,
                name=str(name_val) if name_val is not None and str(name_val) != "nan" else None,
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
