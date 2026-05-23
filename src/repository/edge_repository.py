from sqlalchemy import func, select, update, inspect, text
from src.database.postgresql import get_postgresql_db, engine
from src.entity.walk_network import WalkEdge
from typing import List


class EdgeRepository:
    @staticmethod
    def ensure_score_column(name: str):
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
        with get_postgresql_db() as db:
            db.execute(update(WalkEdge), updates)
            db.commit()