from sqlalchemy import func, select, insert, text
from src.database.postgresql import get_postgresql_db, engine
from src.entity.walk_network import WalkNode
from typing import List


class NodeRepository:
    @staticmethod
    def truncate():
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE walk_nodes RESTART IDENTITY CASCADE"))

    @staticmethod
    def get_max_node_id() -> int:
        with get_postgresql_db() as db:
            result = db.execute(select(func.max(WalkNode.node_id))).scalar()
            return result or 0

    @staticmethod
    def save_all(nodes: List[dict]):
        with get_postgresql_db() as db:
            db.execute(insert(WalkNode), nodes)
            db.commit()
