import logging
from collections.abc import Iterable

from sqlalchemy import delete, insert
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from src.database.postgresql import engine
from src.entity.network.walk_edge import WalkEdge
from src.entity.network.walk_node import WalkNode

logger = logging.getLogger(__name__)


class NetworkWriteRepository:
    """
    기준 도보 네트워크의 NODE·LINK를 하나의 트랜잭션으로 저장합니다.

    upsert는 기존 score를 보존하면서 원본 기반 필드만 갱신하고,
    rebuild는 기존 네트워크를 최신 원본 스냅샷으로 전체 교체합니다.
    """

    DEFAULT_CHUNK_SIZE = 10_000

    @staticmethod
    def _chunks(records: list[dict], chunk_size: int) -> Iterable[list[dict]]:
        for start in range(0, len(records), chunk_size):
            yield records[start:start + chunk_size]

    @classmethod
    def _upsert_records(
        cls,
        connection,
        model,
        records: list[dict],
        primary_key: str,
        chunk_size: int,
    ) -> None:
        if not records:
            return

        insert_statement = postgresql_insert(model)
        update_columns = {
            column_name: insert_statement.excluded[column_name]
            for column_name in records[0]
            if column_name != primary_key
        }
        upsert_statement = insert_statement.on_conflict_do_update(
            index_elements=[getattr(model, primary_key)],
            set_=update_columns,
        )

        for chunk in cls._chunks(records, chunk_size):
            connection.execute(upsert_statement, chunk)

    @classmethod
    def _insert_records(
        cls,
        connection,
        model,
        records: list[dict],
        chunk_size: int,
    ) -> None:
        if not records:
            return
        statement = insert(model)
        for chunk in cls._chunks(records, chunk_size):
            connection.execute(statement, chunk)

    @classmethod
    def upsert(
        cls,
        nodes: list[dict],
        edges: list[dict],
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> None:
        """
        기존 score와 원본에서 사라진 행은 유지하고 NODE·LINK 기본 필드를 갱신합니다.
        """
        with engine.begin() as connection:
            cls._upsert_records(
                connection,
                WalkNode,
                nodes,
                primary_key="node_id",
                chunk_size=chunk_size,
            )
            cls._upsert_records(
                connection,
                WalkEdge,
                edges,
                primary_key="link_id",
                chunk_size=chunk_size,
            )

        logger.info("도보 네트워크 upsert 완료: nodes=%d, edges=%d", len(nodes), len(edges))

    @classmethod
    def rebuild(
        cls,
        nodes: list[dict],
        edges: list[dict],
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> None:
        """
        기존 네트워크를 제거하고 최신 원본 스냅샷으로 전체 재생성합니다.

        WalkEdge score도 초기화되므로 호출 후 활성 Layer collector를 다시 실행해야 합니다.
        """
        with engine.begin() as connection:
            connection.execute(delete(WalkEdge))
            connection.execute(delete(WalkNode))
            cls._insert_records(connection, WalkNode, nodes, chunk_size)
            cls._insert_records(connection, WalkEdge, edges, chunk_size)

        logger.info("도보 네트워크 rebuild 완료: nodes=%d, edges=%d", len(nodes), len(edges))
