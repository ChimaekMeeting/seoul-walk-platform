from src.entity.base import Base
from geoalchemy2 import Geometry
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, String


class LandmarkLayer(Base):
    """
    랜드마크 정보를 관리하는 엔티티입니다.
    """
    __tablename__ = "landmark_layer"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )
    geom = mapped_column(
        Geometry("POINT", srid=4326),
        nullable=False
    )
