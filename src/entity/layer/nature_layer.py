from src.entity.base import Base
from geoalchemy2 import Geometry
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, Integer, String
from typing import Optional


class NatureLayer(Base):
    """
    OSM 녹지 폴리곤(숲, 공원, 초지 등) 정보를 관리하는 엔티티입니다.
    """
    __tablename__ = "nature_layer"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True
    )
    name: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True
    )
    green_type: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True
    )
    green_weight: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True
    )
    geom = mapped_column(
        Geometry("GEOMETRY", srid=4326),
        nullable=False
    )

