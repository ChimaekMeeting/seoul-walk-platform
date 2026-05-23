from sqlalchemy import func, select, update, insert, inspect, text
from src.database.postgresql import get_postgresql_db, engine
from src.entity.walk_network import WalkEdge
from typing import List


class EdgeRepository:
    @staticmethod
    def truncate():
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE walk_edges RESTART IDENTITY CASCADE"))

    @staticmethod
    def save_all(edges: List[dict], chunksize: int = 10000):
        existing_cols = {col["name"] for col in inspect(engine).get_columns("walk_edges")}
        score_defaults = {
            col.name: float(col.server_default.arg)
            for col in WalkEdge.__table__.columns
            if col.server_default is not None and col.name in existing_cols
        }
        with get_postgresql_db() as db:
            for i in range(0, len(edges), chunksize):
                chunk = [{**score_defaults, **e} for e in edges[i:i + chunksize]]
                db.execute(insert(WalkEdge), chunk)
            db.commit()

    @staticmethod
    def ensure_score_column(name: str):
        """
        score 관련 컬럼을 추가합니다. e.g., nature_score
        """
        columns = [col["name"] for col in inspect(engine).get_columns("walk_edges")]
        if name not in columns:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE walk_edges ADD COLUMN {name} FLOAT DEFAULT 0.0"))

    @staticmethod
    def get_link_h3_cells() -> list:
        with get_postgresql_db() as db:
            h3_expr = func.h3_lat_lng_to_cell(func.ST_Centroid(WalkEdge.geom), 9)
            rows = db.execute(
                select(WalkEdge.link_id, h3_expr.label("h3_cell"))
            ).fetchall()
            return rows

    @staticmethod
    def update_scores(updates: List[dict]):
        """
        edge별 score를 업데이트합니다.
        """
        with get_postgresql_db() as db:
            db.execute(update(WalkEdge), updates)
            db.commit()