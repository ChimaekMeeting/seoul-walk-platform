import logging

import geopandas as gpd
import osmnx as ox
from src.repository.raw.osm_raw_repository import OsmRawRepository

logger = logging.getLogger(__name__)


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
        query_key = f"{key}={value}"
        if OsmRawRepository.exists(query_key):
            logger.debug("%s 이미 적재됨, 스킵", query_key)
            return

        logger.info("%s=%s OSM 수집 시작", key, value)
        # 수집
        gdf = ox.features_from_place(self.place, tags={key: value})
        logger.debug("%s=%s 원본 %d행 수집", key, value, len(gdf))

        # 전처리
        gdf = self.clean(gdf, cols=list(gdf.columns), required_cols=[])
        logger.debug("%s=%s 전처리 후 %d행", key, value, len(gdf))

        # 저장
        OsmRawRepository.save(gdf, query_key)
        logger.info("%s=%s 적재 완료: %d행", key, value, len(gdf))

    def store(self) -> None:
        for key, value in self.TAGS:
            self.fetch_and_store(key, value)

    def get(self, key: str, value: str) -> gpd.GeoDataFrame:
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
        # 주요 컬럼 추출
        existing = [c for c in cols if c in gdf.columns]
        keep = list(dict.fromkeys(existing + [gdf.geometry.name]))
        gdf = gdf[keep].copy()

        # 결측치 제거
        null_targets = [c for c in (required_cols if required_cols is not None else existing) if c in gdf.columns]
        if null_targets:
            gdf = gdf.dropna(subset=null_targets)

        # 경위도 중복 데이터 제거 (투영 좌표계로 변환 후 centroid 계산)
        projected = gdf.to_crs(epsg=5179)
        gdf["_cx"] = projected.geometry.centroid.x.round(0)
        gdf["_cy"] = projected.geometry.centroid.y.round(0)
        gdf = gdf.drop_duplicates(subset=["_cx", "_cy"])
        gdf = gdf.drop(columns=["_cx", "_cy"])

        # 컬럼명 수정
        rename_map = {name_col: "name"}
        if addr_col:
            rename_map[addr_col] = "address"
        gdf = gdf.rename(columns=rename_map)

        return gdf.reset_index(drop=True)
