from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional

from src.entity.base import Base


class SeoulAdministrativeBoundary(Base):
    """
    서울시 행정구역 경계 폴리곤 엔티티 (VAL-COORD-004 2차 검증용)
    """
    __tablename__ = "seoul_administrative_boundary"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    geom = mapped_column(Geometry("GEOMETRY", srid=4326), nullable=False)
