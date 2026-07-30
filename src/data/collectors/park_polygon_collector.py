import logging
from pathlib import Path

import geopandas as gpd

from src.repository.layer.nature_repository import NatureRepository

logger = logging.getLogger(__name__)


class ParkPolygonCollector:
    """
    서울시 생활권계획 공원 Polygon을 NatureLayer에 저장하고,
    기존 WalkEdge의 공원 내부 길이 비율을 갱신합니다.

    원본 도보망의 raw_is_park_green과 점수 정책의 nature_score는 수정하지 않습니다.
    """

    RAW_PATH = Path("src/data/raw/서울시 생활권계획 시설(공원) 공간정보.shp")
    BOUNDARY_PATH = Path("src/data/raw/행정구역 법정동 경계.shp")
    GREEN_TYPE = "seoul_park_polygon"
    SOURCE_NAME = "seoul_living_area_plan_park"

    def __init__(
        self,
        raw_path: str | Path | None = None,
        boundary_path: str | Path | None = None,
    ):
        self.raw_path = Path(raw_path) if raw_path is not None else self.RAW_PATH
        self.boundary_path = (
            Path(boundary_path)
            if boundary_path is not None
            else self.BOUNDARY_PATH
        )

    def _load_seoul_boundary(self, crs) -> object:
        if not self.boundary_path.exists():
            raise FileNotFoundError(
                f"행정구역 법정동 경계 Shapefile을 찾을 수 없습니다: "
                f"{self.boundary_path}"
            )
        boundary = gpd.read_file(self.boundary_path, encoding="cp949")
        if boundary.crs is None:
            raise ValueError("행정구역 경계 Shapefile의 좌표계 정보가 없습니다.")
        if "COL_ADM_SE" not in boundary.columns:
            raise ValueError("행정구역 경계에 COL_ADM_SE 자치구 코드가 없습니다.")
        boundary = boundary[
            boundary["COL_ADM_SE"].astype(str).str.startswith("11")
            & boundary.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
        ].copy()
        boundary.geometry = boundary.geometry.make_valid()
        boundary = boundary[
            boundary.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
            & ~boundary.geometry.is_empty
        ]
        if boundary.empty:
            raise ValueError("서울 행정구역 Polygon geometry가 없습니다.")
        return boundary.to_crs(crs).geometry.unary_union

    def build_records(self) -> gpd.GeoDataFrame:
        if not self.raw_path.exists():
            raise FileNotFoundError(f"공원 Shapefile을 찾을 수 없습니다: {self.raw_path}")

        gdf = gpd.read_file(self.raw_path)
        if gdf.crs is None:
            raise ValueError("공원 Shapefile의 좌표계 정보가 없습니다.")

        required_columns = {"ID", "LABEL"}
        missing_columns = required_columns - set(gdf.columns)
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"공원 Shapefile 필수 컬럼이 없습니다: {missing}")

        gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
        if gdf.empty:
            raise ValueError("공원 Shapefile에 Polygon geometry가 없습니다.")

        gdf.geometry = gdf.geometry.make_valid()
        gdf = gdf[
            gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
            & ~gdf.geometry.is_empty
        ].copy()
        if gdf.empty:
            raise ValueError("유효한 공원 Polygon geometry가 없습니다.")

        seoul_boundary = self._load_seoul_boundary(gdf.crs)
        gdf.geometry = gdf.geometry.intersection(seoul_boundary)
        gdf = gdf[
            gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
            & ~gdf.geometry.is_empty
        ].copy()
        if gdf.empty:
            raise ValueError("서울 경계와 교차하는 공원 Polygon이 없습니다.")

        gdf = gdf.to_crs("EPSG:4326")
        gdf["osm_raw_id"] = None
        gdf["green_type"] = self.GREEN_TYPE
        gdf["green_weight"] = 1
        gdf["source_name"] = self.SOURCE_NAME
        gdf["source_id"] = gdf["ID"].astype(str)
        gdf["name"] = gdf["LABEL"].where(gdf["LABEL"].notna(), None)

        if gdf.geometry.name != "geom":
            gdf = gdf.rename_geometry("geom")

        records = gdf[
            [
                "osm_raw_id",
                "green_type",
                "green_weight",
                "source_name",
                "source_id",
                "name",
                "geom",
            ]
        ].reset_index(drop=True)
        logger.info("서울시 공원 Polygon %d개 빌드 완료", len(records))
        return records

    def update_node(self) -> None:
        records = self.build_records()
        NatureRepository.replace_green_type(records, self.GREEN_TYPE)
        logger.info("nature_layer 공원 Polygon %d개 교체 완료", len(records))

    def update_edge(self) -> None:
        updated = NatureRepository.update_edge_park_overlap_ratios(self.GREEN_TYPE)
        logger.info(
            "공원 Polygon 내부 길이 비율 갱신 완료: %d개 WalkEdge 교차",
            updated,
        )

    def save(self) -> None:
        self.update_node()
        self.update_edge()


if __name__ == "__main__":
    ParkPolygonCollector().save()
