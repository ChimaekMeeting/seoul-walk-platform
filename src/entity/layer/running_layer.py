from src.entity.base import Base
from geoalchemy2 import Geometry
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, ForeignKey, String
from typing import Optional


class RunningLayer(Base):
    __tablename__ = "running_layer"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    csv_raw_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("csv_raw.id", ondelete="CASCADE"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    course_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="river | park | bike_track | trail"
    )
    difficulty: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True,
        comment="easy | medium | hard"
    )
    geom = mapped_column(Geometry("GEOMETRY", srid=4326), nullable=True)
