from typing import Optional

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, Boolean, Integer, String, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from src.entity.base import Base


class AccidentProneArea(Base):
    """
    도로교통공단 전국교통사고다발지역표준데이터의 서울 보행 관련 사고다발지역
    원본 폴리곤(EPSG:5179 → 4326 변환)을 그대로 보관합니다.

    CCTV·보안등 커버리지(safety_score)와는 별개 축인 accident_score 계산에만
    쓰이며, 반경으로 새로 만든 원이 아니라 공단이 제공한 폴리곤 원본입니다.
    """
    __tablename__ = "accident_prone_area"
    __table_args__ = (
        Index("idx_accident_prone_area_geog", text("(geom::geography)"), postgresql_using="gist"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    accident_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    accident_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    death_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    has_death: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    geom = mapped_column(Geometry("GEOMETRY", srid=4326, spatial_index=True), nullable=False)
