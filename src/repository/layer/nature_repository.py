import geopandas as gpd
import pandas as pd
from geoalchemy2 import Geography
from sqlalchemy import cast, delete, func, select, text

from src.database.postgresql import get_postgresql_db, engine
from src.entity.layer.nature_layer import NatureLayer
from src.entity.network.walk_edge import WalkEdge
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
    def get_nature_counts_by_edge(radius_m: int = 50) -> dict[int, int]:
        """
        Edge(walk_edges)로부터 반경 radius_m 이내에 있는 NatureLayer 개수를 Edge별로 집계합니다.

        V1 공원 Polygon은 별도 길이 중첩 비율 계산 경로(update_edge_park_overlap_ratios)를
        사용하므로 이 집계에서 제외합니다.

        Returns:
            dict[int, int]: {link_id: count} 형태의 딕셔너리.
        """
        edge_geog = cast(WalkEdge.geom, Geography())
        nature_geog = cast(NatureLayer.geom, Geography())

        with get_postgresql_db() as db:
            rows = db.execute(
                select(WalkEdge.link_id, func.count(NatureLayer.id))
                # join 연산을 할 때는 기준이 되는 테이블을 명시해야 함.
                # 따라서 select_from() 필요
                .select_from(WalkEdge)
                # edge로부터 NatureLayer feature가 radius_m 내에 있고,
                # V1 공원 Polygon(osm_raw_id is null)이 아니면 join
                .join(
                    NatureLayer,
                    func.ST_DWithin(edge_geog, nature_geog, radius_m)
                    & NatureLayer.osm_raw_id.is_not(None),
                )
                .group_by(WalkEdge.link_id)
            ).fetchall()

        return {row.link_id: row[1] for row in rows}
