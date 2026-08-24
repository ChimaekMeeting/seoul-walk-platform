from src.entity.base import Base
from geoalchemy2 import Geometry
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, Boolean, Float, Index, text


class WalkEdge(Base):
    """
    도보 네트워크 엣지(링크) 정보를 관리하는 엔티티입니다.
    """
    __tablename__ = "walk_edges"
    __table_args__ = (
        Index("idx_walk_edges_geog", text("(geom::geography)"), postgresql_using="gist"),
    )

    link_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True
    )
    start_node: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False
    )
    end_node: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False
    )
    length_m: Mapped[float] = mapped_column(
        Float,
        nullable=True
    )
    '''
    safety_score: Mapped[float] = mapped_column(
        Float,
        server_default="0.0"
    )
    nature_score: Mapped[float] = mapped_column(
        Float,
        server_default="0.0"
    )
    slope_score: Mapped[float] = mapped_column(
        Float,
        server_default="0.0"
    )
    running_score: Mapped[float] = mapped_column(
        Float,
        server_default="0.0"
    )
    landmark_score: Mapped[float] = mapped_column(
        Float,
        server_default="0.0"
    )
    child_score: Mapped[float] = mapped_column(
        Float,
        server_default="0.0"
    )
    park_overlap_ratio: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        server_default="0.0",
        comment="Edge 길이 중 서울시 공원 Polygon 내부에 포함되는 비율(0.0~1.0)",
    )
    convenience_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        server_default="0.0",
        comment="상권 등 편의 데이터의 Edge 반경 기반 제한 점수(0.0~1.0)",
    )
    is_school_zone: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
        comment="어린이보호구역 Point의 최근접 50m Edge 후보",
    )
    is_vehicle_caution: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
        comment="차량 주의가 필요한 어린이보호구역 인접 Edge",
    )  
    '''
    geom = mapped_column(
        Geometry("LINESTRING", srid=4326, spatial_index=True),
        nullable=False
    )
