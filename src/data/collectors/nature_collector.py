import geopandas as gpd
import pandas as pd

from src.data.sources.osm_source import OSMSource
from src.data.utils import CollectorUtils
from src.repository.layer.nature_repository import NatureRepository
from src.repository.network.edge_repository import EdgeRepository


class NatureCollector:
    TAG_CONFIG: list[tuple[str, str, int]] = [
        ("natural", "wood",       3),
        ("natural", "scrub",      3),
        ("landuse", "forest",     3),
        ("leisure", "park",       2),
        ("leisure", "garden",     2),
        ("landuse", "grass",      2),
        ("landuse", "meadow",     2),
        ("landuse", "farmland",   1),
        ("landuse", "allotments", 1),
    ]

    def __init__(self):
        self.osm = OSMSource()

    def build_records(self) -> gpd.GeoDataFrame:
        frames = []
        for key, value, weight in self.TAG_CONFIG:
            try:
                gdf = self.osm.get(key, value)
                gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
                gdf = gdf.rename_geometry("geom")
                gdf["green_type"]   = value
                gdf["green_weight"] = weight
                frames.append(gdf[["osm_raw_id", "green_type", "green_weight", "geom"]])
                print(f"{key}={value}: {len(gdf)}개")
            except Exception as e:
                print(f"{key}={value} 실패: {e}")

        return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geom", crs="EPSG:4326")

    def update_node(self) -> None:
        """
        nature_layer를 저장합니다.
        """
        combined = self.build_records()
        NatureRepository.save_geodataframe(combined)

    def update_edge(self) -> None:
        """
        walk_edges.nature_score를 업데이트합니다.
        """
        EdgeRepository.ensure_score_column("nature_score")
        CollectorUtils.update_edge_scores("nature_score", NatureRepository.get_nature_h3_counts())

    def save(self) -> None:
        if NatureRepository.is_populated():
            print("  ⏭️  nature_layer 이미 적재됨, 스킵")
            return
        self.update_node()
        self.update_edge()


if __name__ == "__main__":
    collector = NatureCollector()
    collector.save()
