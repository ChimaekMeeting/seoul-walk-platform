from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional

from src.entity.base import Base


class SeoulWaterPolygon(Base):
    """
    서울시 수계(한강/하천) 폴리곤 엔티티 (VAL-COORD-005 수계 판정용)
    """
    __tablename__ = "seoul_water_polygons"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    water_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    geom = mapped_column(Geometry("GEOMETRY", srid=4326), nullable=False)
