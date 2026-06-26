import logging

import geopandas as gpd
import osmnx as ox
import pandas as pd

from src.repository.layer.water_polygon_repository import WaterPolygonRepository

logger = logging.getLogger(__name__)


class SeoulWaterCollector:
    """
    서울시 수계(한강/하천) 폴리곤을 OSM에서 수집하여 DB에 적재합니다.
    VAL-COORD-005 수계 판정(ST_Within)에 사용됩니다.
    """

    _PLACE = "Seoul, South Korea"

    # natural=water : 한강·저수지 등 면 표현
    # waterway=riverbank : 구형 OSM 태그 (일부 데이터에 잔존)
    TAG_CONFIG: list[tuple[str, str]] = [
        ("natural",  "water"),
        ("waterway", "riverbank"),
    ]

    def build_records(self) -> gpd.GeoDataFrame:
        frames = []
        for key, value in self.TAG_CONFIG:
            try:
                logger.info("OSM 수집 중: %s=%s", key, value)
                gdf = ox.features_from_place(self._PLACE, tags={key: value})
                gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
                if gdf.empty:
                    logger.debug("%s=%s: 폴리곤 없음, 스킵", key, value)
                    continue
                if gdf.geometry.name != "geom":
                    gdf = gdf.rename_geometry("geom")
                gdf = gdf.to_crs("EPSG:4326")
                gdf["water_type"] = value
                frames.append(gdf[["water_type", "geom"]])
                logger.info("%s=%s: %d개 폴리곤 수집", key, value, len(gdf))
            except Exception as e:
                logger.warning("%s=%s 수집 실패: %s", key, value, e)

        if not frames:
            logger.warning("수계 데이터 없음 — 빈 GeoDataFrame 반환")
            return gpd.GeoDataFrame(columns=["water_type", "geom"], geometry="geom", crs="EPSG:4326")

        combined = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geom", crs="EPSG:4326")

        # 중복 폴리곤 제거 (centroid 기준 반올림)
        projected = combined.to_crs(epsg=5179)
        combined["_cx"] = projected.geometry.centroid.x.round(0)
        combined["_cy"] = projected.geometry.centroid.y.round(0)
        before = len(combined)
        combined = combined.drop_duplicates(subset=["_cx", "_cy"])
        combined = combined.drop(columns=["_cx", "_cy"])
        logger.debug("중복 제거: %d → %d개", before, len(combined))

        return combined.reset_index(drop=True)

    def save(self) -> None:
        records = self.build_records()
        if records.empty:
            logger.warning("수계 데이터 없음, 적재 건너뜀")
            return
        WaterPolygonRepository.save_geodataframe(records)
        WaterPolygonRepository.create_spatial_index()
        logger.info("seoul_water_polygons 적재 완료: %d개 폴리곤", len(records))


if __name__ == "__main__":
    SeoulWaterCollector().save()
