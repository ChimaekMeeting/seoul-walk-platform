from src.entity.base import Base
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, Float, String, Boolean
from geoalchemy2 import Geometry

class WalkNode(Base):
    __tablename__ = "walk_nodes"

    node_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    node_type: Mapped[str] = mapped_column(String(20), nullable=True)
    is_underground: Mapped[bool] = mapped_column(Boolean, default=False)
    is_overpass: Mapped[bool] = mapped_column(Boolean, default=False)
    geom = mapped_column(Geometry("POINT", srid=4326), nullable=False)

class WalkEdge(Base):
    __tablename__ = "walk_edges"

    link_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    start_node: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_node: Mapped[int] = mapped_column(BigInteger, nullable=False)
    length_m: Mapped[float] = mapped_column(Float, nullable=True)
    road_type: Mapped[str] = mapped_column(String(20), nullable=True) 
    path_type: Mapped[str] = mapped_column(String(20), default="sidewalk")
    safety_score: Mapped[float] = mapped_column(Float, default=0.0)
    slope_score: Mapped[float] = mapped_column(Float, default=0.0)
    geom = mapped_column(Geometry("LINESTRING", srid=4326), nullable=False)