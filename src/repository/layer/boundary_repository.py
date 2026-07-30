import geopandas as gpd
from sqlalchemy import delete, text

from src.database.postgresql import engine
from src.entity.layer.seoul_administrative_boundary import (
    SeoulAdministrativeBoundary,
)


class BoundaryRepository:
    @staticmethod
    def replace_geodataframe(gdf: gpd.GeoDataFrame) -> None:
        """
        서울 자치구 경계를 원본 스냅샷 전체로 교체합니다.

        삭제와 삽입을 같은 트랜잭션에서 실행하여 중간 실패 시 기존 경계를
        보존합니다.
        """
        if gdf.empty:
            raise ValueError("서울 자치구 경계 원본이 비어 있습니다.")

        with engine.begin() as connection:
            connection.execute(delete(SeoulAdministrativeBoundary))
            gdf.to_postgis(
                "seoul_administrative_boundary",
                connection,
                if_exists="append",
                index=False,
            )
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_seoul_boundary_geom "
                "ON seoul_administrative_boundary USING GIST(geom)"
            ))

    @staticmethod
    def create_spatial_index() -> None:
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_seoul_boundary_geom "
                "ON seoul_administrative_boundary USING GIST(geom)"
            ))
