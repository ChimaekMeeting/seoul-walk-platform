import geopandas as gpd
import osmnx as ox
from src.repository.raw.osm_raw_repository import OsmRawRepository


class OSMSource:
    TAGS: list[tuple[str, str]] = [
        ("natural", "wood"),
        ("natural", "scrub"),
        ("landuse", "forest"),
        ("leisure", "park"),
        ("leisure", "garden"),
        ("landuse", "grass"),
        ("landuse", "meadow"),
        ("landuse", "farmland"),
        ("landuse", "allotments"),
    ]

    def __init__(self, place: str = "Seoul, South Korea"):
        self.place = place

    def fetch_and_store(self, key: str, value: str) -> None:
        """
        단일 태그의 OSM 데이터를 수집하여 DB에 저장합니다. 이미 저장된 경우 스킵합니다.
        """
        query_key = f"{key}={value}"
        if OsmRawRepository.exists(query_key):
            return
        
        # 수집
        gdf = ox.features_from_place(self.place, tags={key: value})

        # 전처리
        gdf = self.clean(gdf, cols=list(gdf.columns), required_cols=[])

        # 저장
        OsmRawRepository.save(gdf, query_key)

    def store(self) -> None:
        """
        모든 태그의 OSM 데이터를 DB에 저장합니다.
        """
        for key, value in self.TAGS:
            self.fetch_and_store(key, value)

    def get(self, key: str, value: str) -> gpd.GeoDataFrame:
        """
        DB에서 OSM 데이터를 조회합니다. 없으면 수집 후 저장합니다.
        """
        query_key = f"{key}={value}"
        if not OsmRawRepository.exists(query_key):
            self.fetch_and_store(key, value)
        return OsmRawRepository.get(query_key)

    def clean(
        self,
        gdf: gpd.GeoDataFrame,
        cols: list[str],
        required_cols: list[str] | None = None,
        name_col: str = "name",
        addr_col: str | None = None,
    ) -> gpd.GeoDataFrame:
        """
        전처리를 수행합니다.
        """
        # 주요 컬럼 추출
        existing = [c for c in cols if c in gdf.columns]
        keep = list(dict.fromkeys(existing + [gdf.geometry.name]))
        gdf = gdf[keep].copy()

        # 결측치 제거
        null_targets = [c for c in (required_cols or existing) if c in gdf.columns]
        if null_targets:
            gdf = gdf.dropna(subset=null_targets)

        # 경위도 데이터 제거
        gdf["_cx"] = gdf.geometry.centroid.x.round(6)
        gdf["_cy"] = gdf.geometry.centroid.y.round(6)
        gdf = gdf.drop_duplicates(subset=["_cx", "_cy"])
        gdf = gdf.drop(columns=["_cx", "_cy"])

        # 컬럼명 수정
        rename_map = {name_col: "name"}
        if addr_col:
            rename_map[addr_col] = "address"
        gdf = gdf.rename(columns=rename_map)

        return gdf.reset_index(drop=True)
