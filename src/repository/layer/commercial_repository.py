from collections import Counter

from sqlalchemy import func, select

from src.database.postgresql import get_postgresql_db
from src.entity.raw.csv_raw import CsvRaw
from src.repository.utils import RepositoryUtils


class CommercialRepository:
    @staticmethod
    def get_unique_h3_counts() -> dict[str, int]:
        """상권 Point를 동일 좌표 한 번만 세어 H3 resolution 9로 집계합니다."""
        with get_postgresql_db() as db:
            rows = db.execute(
                select(
                    func.ST_Y(CsvRaw.geom).label("lat"),
                    func.ST_X(CsvRaw.geom).label("lon"),
                )
                .where(CsvRaw.query_key == "type=commercial")
                .distinct()
            ).fetchall()

        cells = (
            RepositoryUtils.lat_lon_to_h3(row.lat, row.lon)
            for row in rows
        )
        return dict(Counter(cells))
