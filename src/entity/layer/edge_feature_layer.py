from typing import Optional

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.entity.base import Base


class EdgeFeatureLayer(Base):
    """WalkEdge 태그로 확정하기 전 검증할 외부 선형 자료입니다."""

    __tablename__ = "edge_feature_layer"
    __table_args__ = (
        UniqueConstraint(
            "source_name",
            "source_id",
            name="uq_edge_feature_source",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    source_name: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[str] = mapped_column(String(100), nullable=False)
    feature_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default="candidate",
    )
    properties: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    geom = mapped_column(Geometry("LINESTRING", srid=4326), nullable=False)
