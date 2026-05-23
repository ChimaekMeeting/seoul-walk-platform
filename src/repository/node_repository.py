from sqlalchemy import func, select, insert
from src.database.postgresql import get_postgresql_db
from src.entity.walk_network import WalkNode
from typing import List


class NodeRepository:
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
