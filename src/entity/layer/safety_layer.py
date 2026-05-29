from src.entity.base import Base
from geoalchemy2 import Geometry
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, String
from typing import Optional


class SafetyLayer(Base):
    """
    안전 시설물(CCTV, 스마트 가로등) 정보를 관리하는 엔티티입니다.
    """
    __tablename__ = "safety_layer"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True
    )
    safety_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False
    )
    address: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True
    )
    geom = mapped_column(
        Geometry("POINT", srid=4326),
        nullable=False
    )
