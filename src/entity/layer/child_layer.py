from typing import Optional

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from src.entity.base import Base


class ChildLayer(Base):
    """
    어린이보호구역과 어린이놀이시설 정보를 통합 관리하는 엔티티입니다.
    """
    __tablename__ = "child_layer"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    address: Mapped[Optional[str]] = mapped_column(
        String(300),
        nullable=True,
    )
    geom = mapped_column(
        Geometry("POINT", srid=4326),
        nullable=False,
    )
