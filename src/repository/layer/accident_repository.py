import geopandas as gpd
from sqlalchemy import delete, text

from src.database.postgresql import engine
from src.entity.layer.accident_prone_area import AccidentProneArea


class AccidentRepository:
    @staticmethod
    def replace_all(gdf: gpd.GeoDataFrame) -> None:
        """
        사고다발지역 Polygon 원본 전체를 최신 수집 결과로 원자적으로 교체합니다.

        삭제와 삽입을 한 트랜잭션에서 실행하여 중간 실패 시 기존 데이터를 보존합니다.
        """
        if gdf.empty:
            raise ValueError("사고다발지역 원본이 비어 있어 기존 데이터를 교체할 수 없습니다.")

        with engine.begin() as connection:
            connection.execute(delete(AccidentProneArea))
            gdf.to_postgis(
                "accident_prone_area",
                connection,
                if_exists="append",
                index=False,
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_accident_prone_area_geom "
                    "ON accident_prone_area USING GIST(geom)"
                )
            )

    @staticmethod
    def update_edge_accident_overlap_ratios() -> int:
        """
        WalkEdge 길이 중 사고다발지역 Polygon 내부에 포함되는 비율을 accident_score에 저장합니다.

        safety_score(CCTV·보안등 커버리지)와 완전히 별개 축이며, 반경 버퍼 없이
        원본 폴리곤을 그대로 사용합니다. 겹치는 폴리곤을 먼저 union으로 합쳐서
        면적을 dissolve한 뒤 Edge와 딱 한 번만 교차시킵니다 — 개별 폴리곤을
        Edge와 먼저 교차시킨 뒤 그 결과들을 union하면 겹치는 구간에서 길이가
        중복 합산되는 문제가 있습니다(safety_repository.get_safety_coverage_by_edge
        에서 관악구 psql 대조로 확인된 것과 같은 종류의 순서 버그).
        """
        reset_statement = text(
            """
            UPDATE walk_edges
            SET accident_score = 0.0
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
                                    ST_Intersection(
                                        edge.geom,
                                        ST_Union(accident.geom)
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
                JOIN accident_prone_area AS accident
                  ON edge.geom && accident.geom
                 AND ST_Intersects(edge.geom, accident.geom)
                GROUP BY edge.link_id, edge.geom
            )
            UPDATE walk_edges AS edge
            SET accident_score = overlap.overlap_ratio
            FROM overlap_by_edge AS overlap
            WHERE edge.link_id = overlap.link_id
            """
        )
        with engine.begin() as connection:
            connection.execute(reset_statement)
            result = connection.execute(overlap_statement)
        return result.rowcount
