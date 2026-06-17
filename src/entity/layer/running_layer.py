from src.entity.base import Base
from geoalchemy2 import Geometry
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, String
from typing import Optional


class RunningLayer(Base):
    """
    런닝/다이어트에 적합한 코스 정보를 관리하는 엔티티입니다.
    """
    __tablename__ = "running_layer"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False
    )
    course_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="river | park | bike_track | trail"
    )
    difficulty: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="easy | medium | hard"
    )
    geom = mapped_column(
        Geometry("GEOMETRY", srid=4326),
        nullable=True
    )
