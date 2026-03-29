from src.entity.base import Base
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, String, Integer
from geoalchemy2 import Geometry

# 1. 안전 시설물 (CCTV, 스마트 가로등)
class SafetyPoint(Base):
    __tablename__ = "safety_layer"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    safety_type: Mapped[str] = mapped_column(String(50)) # 'cCTV', 'streetlight' 등
    address: Mapped[str] = mapped_column(String(200), nullable=True)
    geom = mapped_column(Geometry("POINT", srid=4326), nullable=False)

# 2. 편의/테마 시설물 (공원, 가로수길 입구)
class PoiPoint(Base):
    __tablename__ = "poi_layer"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    poi_type: Mapped[str] = mapped_column(String(50)) # 'park', 'tree_road' 등
    name: Mapped[str] = mapped_column(String(100), nullable=True)
    geom = mapped_column(Geometry("POINT", srid=4326), nullable=False)