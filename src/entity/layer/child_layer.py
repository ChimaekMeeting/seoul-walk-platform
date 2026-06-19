from typing import Optional

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from src.entity.base import Base


class ChildLayer(Base):
    __tablename__ = "child_layer"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    csv_raw_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("csv_raw.id", ondelete="CASCADE"),
        nullable=True,
    )
    public_raw_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("public_raw.id", ondelete="CASCADE"),
        nullable=True,
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    geom = mapped_column(Geometry("POINT", srid=4326), nullable=False)
