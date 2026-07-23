from collections import Counter

import geopandas as gpd
import pandas as pd
from sqlalchemy import delete, func, select, text

from src.database.postgresql import get_postgresql_db, engine
from src.entity.layer.nature_layer import NatureLayer
from src.repository.utils import RepositoryUtils


class NatureRepository:
    @staticmethod
    def get(lat: float, lon: float, radius_m: int = 2000) -> pd.DataFrame:
        """
        반경 내 녹지 포인트(폴리곤은 centroid 기준) 전체를 조회합니다.
        green_type을 category로 노출합니다.
        """
        return RepositoryUtils.fetch_nearby_points(
            NatureLayer, lat, lon, radius_m, category_col=NatureLayer.green_type,
        )

    @staticmethod
    def save_geodataframe(gdf: gpd.GeoDataFrame) -> None:
        """
        OSM 녹지 폴리곤 GeoDataFrame을 nature_layer 테이블에 저장합니다. 중심점 경위도가 같으면 스킵합니다.
        """
        if gdf.empty:
            return
        with get_postgresql_db() as db:
            rows = db.execute(
                select(
                    func.ST_Y(func.ST_Centroid(NatureLayer.geom)).label("lat"),
                    func.ST_X(func.ST_Centroid(NatureLayer.geom)).label("lon"),
                )
            ).fetchall()
        existing = {(round(float(r.lat), 6), round(float(r.lon), 6)) for r in rows}
        centroids = gdf.geometry.centroid
        mask = [(round(c.y, 6), round(c.x, 6)) not in existing for c in centroids]
        gdf = gdf[mask]
        if gdf.empty:
            return
        gdf.to_postgis("nature_layer", engine, if_exists="append", index=False)

    @staticmethod
    def replace_green_type(gdf: gpd.GeoDataFrame, green_type: str) -> None:
        """
        특정 green_type의 Polygon Layer를 최신 원본 전체로 교체합니다.

        삭제와 삽입을 한 트랜잭션에서 실행하여 중간 실패 시 기존 Layer를 보존합니다.
        """
        if gdf.empty:
            raise ValueError(f"{green_type} 원본이 비어 있어 기존 Layer를 교체할 수 없습니다.")

        with engine.begin() as connection:
            connection.execute(
                delete(NatureLayer).where(NatureLayer.green_type == green_type)
            )
            gdf.to_postgis(
                "nature_layer",
                connection,
                if_exists="append",
                index=False,
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_nature_layer_geom "
                    "ON nature_layer USING GIST(geom)"
                )
            )

    @staticmethod
    def update_edge_park_overlap_ratios(green_type: str) -> int:
        """
        WalkEdge 길이 중 지정 공원 Polygon 내부에 포함되는 비율을 저장합니다.

        겹치는 공원 Polygon은 Edge별로 합친 뒤 길이를 계산하므로 중복 면적을
        두 번 더하지 않습니다. raw_is_park_green과 nature_score는 수정하지 않습니다.
        """
        reset_statement = text(
            """
            UPDATE walk_edges
            SET park_overlap_ratio = 0.0
            """
        )
        overlap_statement = text(
            """
            WITH overlap_by_edge AS (
                SELECT
                    edge.link_id,
                    LEAST(
                        1.0,
                        COALESCE(
                            ST_Length(
                                ST_Transform(
                                    ST_UnaryUnion(
                                        ST_Collect(
                                            ST_Intersection(edge.geom, nature.geom)
                                        )
                                    ),
                                    5179
                                )
                            )
                            / NULLIF(
                                ST_Length(ST_Transform(edge.geom, 5179)),
                                0.0
                            ),
                            0.0
                        )
                    ) AS overlap_ratio
                FROM walk_edges AS edge
                JOIN nature_layer AS nature
                  ON nature.green_type = :green_type
                 AND edge.geom && nature.geom
                 AND ST_Intersects(edge.geom, nature.geom)
                GROUP BY edge.link_id, edge.geom
            )
            UPDATE walk_edges AS edge
            SET park_overlap_ratio = overlap.overlap_ratio
            FROM overlap_by_edge AS overlap
            WHERE edge.link_id = overlap.link_id
            """
        )
        with engine.begin() as connection:
            connection.execute(reset_statement)
            result = connection.execute(
                overlap_statement,
                {"green_type": green_type},
            )
        return result.rowcount

    @staticmethod
    def get_nature_h3_counts() -> dict[str, int]:
        """
        기존 OSM 녹지의 H3 셀(resolution 9)별 폴리곤 개수를 반환합니다.

        V1 공원 Polygon은 별도 길이 중첩 비율 계산 경로를 사용하므로 이 집계에서 제외합니다.
        폴리곤의 중심점(centroid)을 기준으로 H3 셀을 계산합니다.
        """
        lat_expr, lon_expr = RepositoryUtils.geom_centroid_lat_lon(NatureLayer.geom)
        with get_postgresql_db() as db:
            rows = db.execute(
                select(lat_expr.label("lat"), lon_expr.label("lon"))
                .where(NatureLayer.osm_raw_id.is_not(None))
            ).fetchall()
        cells = (RepositoryUtils.lat_lon_to_h3(row.lat, row.lon) for row in rows)
        return dict(Counter(cells))
