from src.entity.base import Base
from geoalchemy2 import Geometry
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, Boolean, String


class WalkNode(Base):
    """
    도보 네트워크 노드 정보를 관리하는 엔티티입니다.
    """
    __tablename__ = "walk_nodes"

    node_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True
    )
    node_type: Mapped[str] = mapped_column(
        String(20),
        nullable=True
    )
    is_underground: Mapped[bool] = mapped_column(
        Boolean,
        default=False
    )
    is_overpass: Mapped[bool] = mapped_column(
        Boolean,
        default=False
    )
    geom = mapped_column(
        Geometry("POINT", srid=4326),
        nullable=False
    )
