import osmnx as ox
import geopandas as gpd
import pandas as pd

from src.repository.layer.nature_repository import NatureRepository
from src.repository.network.edge_repository import EdgeRepository


class NatureCollector:
    """
    OpenStreetMap에서 서울 녹지 폴리곤을 수집하여 nature_layer 테이블에 저장하고
    walk_edges.nature_score를 거리 기반으로 업데이트합니다.
    """

    TAG_CONFIG = [
        ({"natural": ["wood", "scrub"], "landuse": ["forest"]}, 3),
        ({"leisure": ["park", "garden"], "landuse": ["grass", "meadow"]}, 2),
        ({"landuse": ["farmland", "allotments"]}, 1),
    ]

    def build_records(self) -> gpd.GeoDataFrame:
        """
        태그 설정별로 OSM 녹지 피처를 조회하여 하나의 GeoDataFrame으로 합칩니다.
        """
        frames = []
        for tags, weight in self.TAG_CONFIG:
            for key, values in tags.items():
                for val in values:
                    try:
                        gdf = ox.features_from_place("Seoul, South Korea", tags={key: val})
                        gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
                        gdf = gdf.rename_geometry("geom")
                        gdf["name"]         = gdf["name"] if "name" in gdf.columns else None
                        gdf["green_type"]   = val
                        gdf["green_weight"] = weight
                        frames.append(gdf[["name", "green_type", "green_weight", "geom"]])
                        print(f"{key}={val}: {len(gdf)}개")
                    except Exception as e:
                        print(f"{key}={val} 실패: {e}")

        return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geom", crs="EPSG:4326")

    def update_node(self) -> None:
        """
        nature_layer를 초기화하고 OSM 녹지 폴리곤을 저장합니다.
        """
        NatureRepository.truncate()
        combined = self.build_records()
        NatureRepository.save_geodataframe(combined)
        print(f"  ✅ 총 {len(combined)}개 폴리곤 저장 완료")

    def update_edge(self) -> None:
        """
        nature_layer 거리 기반으로 walk_edges.nature_score를 업데이트합니다.
        """
        EdgeRepository.reset_nature_score()
        count = EdgeRepository.update_nature_score_from_osm()
        print(f"  ✅ nature_score 업데이트 완료: {count}개 엣지")

    def save(self) -> None:
        """
        nature_layer를 저장한 뒤 walk_edges.nature_score를 업데이트합니다.
        """
        self.update_node()
        self.update_edge()


if __name__ == "__main__":
    collector = NatureCollector()
    collector.save()
