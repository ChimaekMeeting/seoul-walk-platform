from src.entity.base import Base
from geoalchemy2 import Geometry
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, ForeignKey, Integer, String
from typing import Optional


class NatureLayer(Base):
    """
    OSM 녹지와 승인된 공원 Polygon 등 자연 영역 정보를 관리합니다.
    """
    __tablename__ = "nature_layer"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True
    )
    osm_raw_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("osm_raw.id", ondelete="CASCADE"),
        nullable=True,
    )
    green_type: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True
    )
    green_weight: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True
    )
    source_name: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    source_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    name: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
    )
    geom = mapped_column(
        Geometry("GEOMETRY", srid=4326),
        nullable=False
    )
