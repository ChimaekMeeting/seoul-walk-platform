from src.entity.base import Base
from geoalchemy2 import Geometry
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, Index, text


class WalkNode(Base):
    """
    도보 네트워크 노드 정보를 관리하는 엔티티입니다.
    """
    __tablename__ = "walk_nodes"
    __table_args__ = (
        Index("idx_walk_nodes_geog", text("(geom::geography)"), postgresql_using="gist"),
    )

    node_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True
    )
    geom = mapped_column(
        Geometry("POINT", srid=4326),
        nullable=False
    )
