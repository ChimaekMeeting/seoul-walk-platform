from src.entity.base import Base
from geoalchemy2 import Geometry
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, ForeignKey, Index, String, text
from typing import Optional


class SafetyLayer(Base):
    __tablename__ = "safety_layer"
    __table_args__ = (
        Index("idx_safety_layer_geog", text("(geom::geography)"), postgresql_using="gist"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    csv_raw_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("csv_raw.id", ondelete="CASCADE"),
        nullable=True,
    )
    safety_type: Mapped[str] = mapped_column(String(50), nullable=False)
    geom = mapped_column(Geometry("POINT", srid=4326, spatial_index=True), nullable=False)
