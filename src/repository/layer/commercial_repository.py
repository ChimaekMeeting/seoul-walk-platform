from geoalchemy2 import Geography
from sqlalchemy import cast, func, select

from src.database.postgresql import get_postgresql_db
from src.entity.network.walk_edge import WalkEdge
from src.entity.raw.csv_raw import CsvRaw


class CommercialRepository:
    @staticmethod
    def get_commercial_counts_by_edge(radius_m: int = 50) -> dict[int, int]:
        """
        Edge(walk_edges)로부터 반경 radius_m 이내에 있는 상권 Point 개수를 Edge별로 집계합니다.
        동일 좌표는 한 번만 셉니다.

        Returns:
            dict[int, int]: {link_id: count} 형태의 딕셔너리.
        """
        # 동일 좌표 상권 Point를 먼저 한 번만 남기고(subquery), 그 결과를 Edge와 반경 join.
        distinct_commercial = (
            select(CsvRaw.geom)
            .where(CsvRaw.query_key == "type=commercial")
            .distinct()
            .subquery()
        )

        edge_geog = cast(WalkEdge.geom, Geography())
        commercial_geog = cast(distinct_commercial.c.geom, Geography())

        with get_postgresql_db() as db:
            rows = db.execute(
                select(WalkEdge.link_id, func.count(distinct_commercial.c.geom))
                # join 연산을 할 때는 기준이 되는 테이블을 명시해야 함.
                # 따라서 select_from() 필요
                .select_from(WalkEdge)
                # edge로부터 상권 Point(중복 제거됨)가 radius_m 내에 있으면 join
                .join(distinct_commercial, func.ST_DWithin(edge_geog, commercial_geog, radius_m))
                .group_by(WalkEdge.link_id)
            ).fetchall()

        return {row.link_id: row[1] for row in rows}
