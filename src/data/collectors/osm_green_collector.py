import osmnx as ox
import geopandas as gpd
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

load_dotenv(dotenv_path=Path(__file__).parent / ".env", encoding="utf-8")

from src.database.postgresql import engine  # 기존 engine 재사용

TAG_CONFIG = [
    ({"natural": ["wood", "scrub"], "landuse": ["forest"]}, 3),
    ({"leisure": ["park", "garden"], "landuse": ["grass", "meadow"]}, 2),
    ({"landuse": ["farmland", "allotments"]}, 1),
]

frames = []
for tags, weight in TAG_CONFIG:
    for key, values in tags.items():
        for val in values:
            try:
                gdf = ox.features_from_place("Seoul, South Korea", tags={key: val})
                gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
                gdf["osm_id"] = gdf.index.get_level_values("osmid")
                gdf["green_type"] = val
                gdf["green_weight"] = weight
                gdf["name"] = gdf["name"] if "name" in gdf.columns else None
                frames.append(gdf[["osm_id", "green_type", "green_weight", "name", "geometry"]])
                print(f"{key}={val}: {len(gdf)}개")
            except Exception as e:
                print(f"{key}={val} 실패: {e}")

combined = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:4326")
combined.to_postgis("osm_green_areas", engine, if_exists="append", index=False)
print(f"총 {len(combined)}개 폴리곤 저장 완료")