from sqlalchemy import func, select, insert, inspect, text
from src.database.postgresql import get_postgresql_db, engine
from src.entity.network.walk_node import WalkNode
from typing import List


class NodeRepository:
    @staticmethod
    def save_all(nodes: List[dict]):
        """
        노드 데이터를 walk_nodes에 벌크 저장합니다. 이미 같은 node_id가 있으면 스킵합니다.
        """
        if not nodes:
            return
        with get_postgresql_db() as db:
            existing_ids = set(db.execute(select(WalkNode.node_id)).scalars())
            new_nodes = [n for n in nodes if n["node_id"] not in existing_ids]
            if not new_nodes:
                return
            db.execute(insert(WalkNode), new_nodes)
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

    @staticmethod
    def ensure_column(name: str, sql_type: str = "FLOAT"):
        """
        walk_nodes 테이블에 컬럼이 없으면 추가합니다.
        EdgeRepository.ensure_score_column()과 같은 방식으로,
        기본 스키마를 최소로 유지하면서 필요한 collector가 자기 컬럼을 확보합니다.
        """
        columns = [col["name"] for col in inspect(engine).get_columns("walk_nodes")]
        if name not in columns:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE walk_nodes ADD COLUMN {name} {sql_type}"))

    @staticmethod
    def update_elevations(elevations: dict):
        """
        {node_id: elevation_m} 을 walk_nodes.elevation_m 에 일괄 저장합니다.

        고도를 얻지 못한 노드(None)는 건너뜁니다. 값을 보존해두면 경사 임계값을
        바꿀 때 DEM 재샘플링 없이 SQL만으로 재계산할 수 있습니다.
        """
        items = [(nid, v) for nid, v in elevations.items() if v is not None]
        if not items:
            return
        NodeRepository.ensure_column("elevation_m")
        ids  = [i[0] for i in items]
        vals = [float(i[1]) for i in items]
        with engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE walk_nodes w
                    SET elevation_m = t.val
                    FROM unnest(CAST(:ids AS bigint[]), CAST(:vals AS float[])) AS t(node_id, val)
                    WHERE w.node_id = t.node_id
                """),
                {"ids": ids, "vals": vals},
            )
