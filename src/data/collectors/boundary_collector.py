import logging
from pathlib import Path

import geopandas as gpd

from src.repository.layer.boundary_repository import BoundaryRepository

logger = logging.getLogger(__name__)


class SeoulBoundaryCollector:
    """
    법정동 Shapefile을 서울 25개 자치구 경계로 합쳐 DB에 적재합니다.

    VAL-COORD-004 2차 검증(ST_Within)에 사용됩니다.
    """

    RAW_PATH = Path("src/data/raw/행정구역 법정동 경계.shp")
    DISTRICT_NAMES = {
        "11110": "종로구",
        "11140": "중구",
        "11170": "용산구",
        "11200": "성동구",
        "11215": "광진구",
        "11230": "동대문구",
        "11260": "중랑구",
        "11290": "성북구",
        "11305": "강북구",
        "11320": "도봉구",
        "11350": "노원구",
        "11380": "은평구",
        "11410": "서대문구",
        "11440": "마포구",
        "11470": "양천구",
        "11500": "강서구",
        "11530": "구로구",
        "11545": "금천구",
        "11560": "영등포구",
        "11590": "동작구",
        "11620": "관악구",
        "11650": "서초구",
        "11680": "강남구",
        "11710": "송파구",
        "11740": "강동구",
    }

    def __init__(self, raw_path: str | Path | None = None):
        self.raw_path = Path(raw_path) if raw_path is not None else self.RAW_PATH

    def build_records(self) -> gpd.GeoDataFrame:
        if not self.raw_path.exists():
            raise FileNotFoundError(
                f"행정구역 법정동 경계 Shapefile을 찾을 수 없습니다: {self.raw_path}"
            )

        gdf = gpd.read_file(self.raw_path, encoding="cp949")
        if gdf.crs is None:
            raise ValueError("행정구역 경계 Shapefile의 좌표계 정보가 없습니다.")
        if "COL_ADM_SE" not in gdf.columns:
            raise ValueError("행정구역 경계에 COL_ADM_SE 자치구 코드가 없습니다.")

        gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
        gdf.geometry = gdf.geometry.make_valid()
        gdf = gdf[
            gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
            & ~gdf.geometry.is_empty
        ].copy()
        if gdf.empty:
            raise ValueError("유효한 법정동 Polygon geometry가 없습니다.")

        gdf["district_code"] = gdf["COL_ADM_SE"].astype(str).str.zfill(5)
        unknown_codes = set(gdf["district_code"]) - set(self.DISTRICT_NAMES)
        if unknown_codes:
            unknown = ", ".join(sorted(unknown_codes))
            raise ValueError(f"알 수 없는 서울 자치구 코드가 있습니다: {unknown}")

        districts = gdf[["district_code", "geometry"]].dissolve(
            by="district_code",
            as_index=False,
        )
        if len(districts) != 25:
            raise ValueError(
                f"서울 자치구 경계는 25개여야 합니다: 현재 {len(districts)}개"
            )

        districts["name"] = districts["district_code"].map(self.DISTRICT_NAMES)
        districts = districts.to_crs("EPSG:4326")
        if districts.geometry.name != "geom":
            districts = districts.rename_geometry("geom")

        logger.info(
            "법정동 %d개를 서울 자치구 %d개 경계로 병합",
            len(gdf),
            len(districts),
        )
        return districts[["district_code", "name", "geom"]].reset_index(drop=True)

    def save(self) -> None:
        records = self.build_records()
        BoundaryRepository.replace_geodataframe(records)
        logger.info(
            "seoul_administrative_boundary 적재 완료: %d개 자치구",
            len(records),
        )


if __name__ == "__main__":
    SeoulBoundaryCollector().save()
