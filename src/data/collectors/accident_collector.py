import json
import logging
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape

from src.repository.layer.accident_repository import AccidentRepository
from src.repository.network.edge_repository import EdgeRepository

logger = logging.getLogger(__name__)


class AccidentCollector:
    """
    도로교통공단 전국교통사고다발지역표준데이터의 서울 보행 관련 사고다발지역
    Polygon을 accident_prone_area에 적재하고, WalkEdge의 accident_score
    (Polygon 커버리지 비율)를 갱신합니다.

    CCTV·보안등 기반 safety_score(가점)와 완전히 별개 축이며(페널티), 반경으로
    새로 원을 그리지 않고 원본 폴리곤(EPSG:5179)을 그대로 사용합니다.
    """

    RAW_PATH = Path("src/data/raw/전국교통사고다발지역표준데이터.csv")
    PEDESTRIAN_TYPES = ("보행노인", "보행어린이", "스쿨존어린이")
    MIN_YEAR = 2022

    def __init__(self, raw_path: str | Path | None = None):
        self.raw_path = Path(raw_path) if raw_path is not None else self.RAW_PATH

    @staticmethod
    def _parse_polygon(raw: str):
        """
        원본 '사고다발지역폴리곤정보' 값은 키·type 값에 따옴표가 없는 준-JSON
        형태라 표준 JSON으로 보정한 뒤 파싱합니다.
        """
        fixed = re.sub(r'\b(type|coordinates)\s*:', r'"\1":', raw)
        fixed = re.sub(r'"type":\s*([A-Za-z]+)', r'"type": "\1"', fixed)
        return shape(json.loads(fixed))

    def build_records(self) -> gpd.GeoDataFrame:
        if not self.raw_path.exists():
            raise FileNotFoundError(f"사고다발지역 원본을 찾을 수 없습니다: {self.raw_path}")

        df = pd.read_csv(self.raw_path, encoding="cp949")
        df = df[
            df["사고다발지역시도시군구"].astype("string").str.contains("서울", na=False)
        ].copy()
        df = df[df["사고유형구분"].isin(self.PEDESTRIAN_TYPES)].copy()
        df = df[df["사고연도"] >= self.MIN_YEAR].copy()

        if df.empty:
            logger.warning("조건에 맞는 서울 보행 사고다발지역이 없습니다.")
            return gpd.GeoDataFrame(
                columns=["accident_type", "accident_year", "death_count", "has_death", "geom"],
                geometry="geom",
                crs="EPSG:4326",
            )

        geometries = []
        keep_mask = []
        for raw in df["사고다발지역폴리곤정보"]:
            try:
                geometries.append(self._parse_polygon(raw))
                keep_mask.append(True)
            except Exception:
                geometries.append(None)
                keep_mask.append(False)

        dropped = keep_mask.count(False)
        if dropped:
            logger.warning("사고다발지역 Polygon 파싱 실패 %d건 제외", dropped)

        df = df[keep_mask].copy()
        df["geom"] = [g for g, keep in zip(geometries, keep_mask) if keep]
        df["accident_type"] = df["사고유형구분"]
        df["accident_year"] = df["사고연도"]
        df["death_count"] = df["사망자수"]
        df["has_death"] = df["사망자수"] > 0

        gdf = gpd.GeoDataFrame(
            df[["accident_type", "accident_year", "death_count", "has_death", "geom"]],
            geometry="geom",
            crs="EPSG:5179",
        )
        gdf = gdf.to_crs("EPSG:4326")
        logger.info(
            "서울 보행 사고다발지역 %d건 빌드 완료 (%d년~, %s)",
            len(gdf), self.MIN_YEAR, ", ".join(self.PEDESTRIAN_TYPES),
        )
        return gdf

    def update_node(self) -> None:
        gdf = self.build_records()
        AccidentRepository.replace_all(gdf)
        logger.info("accident_prone_area %d건 교체 완료", len(gdf))

    def update_edge(self) -> None:
        EdgeRepository.ensure_score_column("accident_score")
        updated = AccidentRepository.update_edge_accident_overlap_ratios()
        logger.info("사고다발지역 Polygon 커버리지(accident_score) 갱신 완료: %d개 WalkEdge 교차", updated)

    def save(self) -> None:
        self.update_node()
        self.update_edge()


if __name__ == "__main__":
    AccidentCollector().save()
