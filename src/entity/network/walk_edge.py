from src.entity.base import Base
from geoalchemy2 import Geometry
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, Float, Index, text


class WalkEdge(Base):
    """
    도보 네트워크 엣지(링크) 정보를 관리하는 엔티티입니다.
    """
    __tablename__ = "walk_edges"
    __table_args__ = (
        Index("idx_walk_edges_geog", text("(geom::geography)"), postgresql_using="gist"),
    )

    link_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True
    )
    start_node: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False
    )
    end_node: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False
    )
    length_m: Mapped[float] = mapped_column(
        Float,
        nullable=True
    )
    geom = mapped_column(
        Geometry("LINESTRING", srid=4326, spatial_index=True),
        nullable=False
    )
