from src.entity.base import Base
from geoalchemy2 import Geometry
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, Float, String


class WalkEdge(Base):
    """
    도보 네트워크 엣지(링크) 정보를 관리하는 엔티티입니다.
    """
    __tablename__ = "walk_edges"

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
    road_type: Mapped[str] = mapped_column(
        String(20),
        nullable=True
    )
    path_type: Mapped[str] = mapped_column(
        String(20),
        default="sidewalk"
    )
    safety_score: Mapped[float] = mapped_column(
        Float,
        server_default="0.0"
    )
    nature_score: Mapped[float] = mapped_column(
        Float,
        server_default="0.0"
    )
    slope_score: Mapped[float] = mapped_column(
        Float,
        server_default="0.0"
    )
    landmark_score: Mapped[float] = mapped_column(
        Float,
        server_default="0.0"
    )
    geom = mapped_column(
        Geometry("LINESTRING", srid=4326),
        nullable=False
    )
