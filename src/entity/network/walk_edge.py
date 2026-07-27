from src.entity.base import Base
from geoalchemy2 import Geometry
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, Boolean, Float, String


class WalkEdge(Base):
    """
    도보 네트워크 엣지(링크) 정보를 관리하는 엔티티입니다.
    """
    __tablename__ = "walk_edges"

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
    raw_link_type_code: Mapped[str] = mapped_column(
        String(4),
        nullable=False,
    )
    allows_pedestrian: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    allows_vehicle: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    allows_bicycle: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    allows_pm: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    is_walkable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    raw_is_elevated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    raw_is_subway_network: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    raw_is_bridge: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    raw_is_tunnel: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    raw_is_overpass: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    raw_is_crosswalk: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    raw_is_park_green: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    raw_is_building_inside: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    length_m: Mapped[float] = mapped_column(
        Float,
        nullable=True
    )
    safety_score: Mapped[float] = mapped_column(
        Float,
        server_default="0.0"
    )
    nature_score: Mapped[float] = mapped_column(
        Float,
        server_default="0.0"
    )
    park_overlap_ratio: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        server_default="0.0",
        comment="Edge 길이 중 서울시 공원 Polygon 내부에 포함되는 비율(0.0~1.0)",
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
    geom = mapped_column(
        Geometry("LINESTRING", srid=4326),
        nullable=False
    )
