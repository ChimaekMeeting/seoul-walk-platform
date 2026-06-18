import osmnx as ox
import geopandas as gpd


class OSMSource:
    cache: dict[str, gpd.GeoDataFrame] = {}

    def __init__(self, place: str = "Seoul, South Korea"):
        self._place = place

    def get(self, tags: dict) -> gpd.GeoDataFrame:
        """
        OSM에서 태그 기반으로 피처를 수집합니다.
        """
        key = f"{self._place}::{sorted(tags.items())}"
        if key not in self.cache:
            self.cache[key] = ox.features_from_place(self._place, tags=tags)
        return self.cache[key].copy()

    def clean(
        self,
        gdf: gpd.GeoDataFrame,
        cols: list[str],
    ) -> gpd.GeoDataFrame:
        """
        기본 전처리를 수행합니다.
        """
        # 주요 컬럼 추출
        existing = [c for c in cols if c in gdf.columns]
        keep = list(dict.fromkeys(existing + [gdf.geometry.name]))
        gdf = gdf[keep].copy()

        # 결측치 제거
        if existing:
            gdf = gdf.dropna(subset=existing)

        # 경위도 중복 데이터 제거
        gdf["_cx"] = gdf.geometry.centroid.x.round(6)
        gdf["_cy"] = gdf.geometry.centroid.y.round(6)
        gdf = gdf.drop_duplicates(subset=["_cx", "_cy"])
        gdf = gdf.drop(columns=["_cx", "_cy"])

        return gdf.reset_index(drop=True)
