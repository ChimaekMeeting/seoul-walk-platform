import geopandas as gpd
import osmnx as ox

from src.repository.layer.boundary_repository import BoundaryRepository


class SeoulBoundaryCollector:
    """
    서울시 행정구역 경계 폴리곤을 OSM에서 수집하여 DB에 적재합니다.
    VAL-COORD-004 2차 검증(ST_Within)에 사용됩니다.
    """

    _PLACE = "Seoul, South Korea"

    def build_records(self) -> gpd.GeoDataFrame:
        print(f"  OSM에서 서울 행정구역 경계 수집 중...")
        gdf = ox.geocode_to_gdf(self._PLACE)
        gdf = gdf.to_crs("EPSG:4326")

        name_col = "display_name" if "display_name" in gdf.columns else None
        gdf["name"] = gdf[name_col].apply(lambda x: str(x).split(",")[0]) if name_col else "서울특별시"

        if gdf.geometry.name != "geom":
            gdf = gdf.rename_geometry("geom")

        return gdf[["name", "geom"]].reset_index(drop=True)

    def save(self) -> None:
        if BoundaryRepository.is_populated():
            print("  ⏭️  seoul_administrative_boundary 이미 적재됨, 스킵")
            return
        records = self.build_records()
        BoundaryRepository.save_geodataframe(records)
        BoundaryRepository.create_spatial_index()
        print(f"  ✅ seoul_administrative_boundary 적재 완료: {len(records)}개 폴리곤")


if __name__ == "__main__":
    SeoulBoundaryCollector().save()
