from sqlalchemy import func, select, insert, text
from src.database.postgresql import get_postgresql_db, engine
from src.entity.network.walk_node import WalkNode
from typing import List


class NodeRepository:
    @staticmethod
    def truncate():
        """
        walk_nodes 테이블의 모든 데이터를 초기화합니다.
        시퀀스(ID)도 함께 리셋하며, 연관 테이블에 CASCADE 적용합니다.
        """
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE walk_nodes RESTART IDENTITY CASCADE"))

    @staticmethod
    def get_max_node_id() -> int:
        """
        walk_nodes 테이블에서 현재 최대 node_id를 반환합니다.

        Returns:
            int: 최대 node_id 값. 테이블이 비어 있으면 0을 반환합니다.
        """
        with get_postgresql_db() as db:
            result = db.execute(select(func.max(WalkNode.node_id))).scalar()
            return result or 0

    @staticmethod
    def save_all(nodes: List[dict]):
        """
        노드 데이터를 walk_nodes에 벌크 저장합니다.

        Args:
            nodes : 저장할 노드 딕셔너리 목록.
        """
        with get_postgresql_db() as db:
            db.execute(insert(WalkNode), nodes)
            db.commit()

    @staticmethod
    def get_all_coordinates() -> list:
        """
        walk_nodes 전체의 (node_id, lon, lat) 목록을 반환합니다.

        Returns:
            list: (node_id, lon, lat) 행 리스트.
        """
        with get_postgresql_db() as db:
            return db.execute(
                select(
                    WalkNode.node_id,
                    func.ST_X(WalkNode.geom).label("lon"),
                    func.ST_Y(WalkNode.geom).label("lat"),
                ).order_by(WalkNode.node_id)
            ).fetchall()
