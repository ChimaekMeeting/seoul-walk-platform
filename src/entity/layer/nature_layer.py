from src.entity.base import Base
from geoalchemy2 import Geometry
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, String
from typing import Optional


class NaturePoint(Base):
    """
    자연/녹지 시설물(공원, 가로수길 입구) 정보를 관리하는 엔티티입니다.
    """
    __tablename__ = "poi_layer"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True
    )
    poi_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False
    )
    name: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True
    )
    geom = mapped_column(
        Geometry("POINT", srid=4326),
        nullable=False
    )
