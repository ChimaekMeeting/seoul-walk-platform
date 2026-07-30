from typing import Optional

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, Boolean, Float, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.entity.base import Base


class RoutePoi(Base):
    """경로 주변 편의·교통·접근성 시설과 도보망 연결을 저장합니다."""

    __tablename__ = "route_pois"
    __table_args__ = (
        UniqueConstraint("source_name", "source_id", name="uq_route_poi_source"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    source_name: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    nearest_node_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
        index=True,
    )
    nearest_edge_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
        index=True,
    )
    distance_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_route_connected: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )
    properties: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    geom = mapped_column(Geometry("POINT", srid=4326), nullable=False)
