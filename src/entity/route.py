from src.entity.base import Base
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Integer, String, Float, DateTime, func, JSON
from datetime import datetime
from typing import Optional

class Route(Base):
    """
    사용자의 이동 경로 또는 추천 경로 정보를 저장합니다.
    """
    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(
        Integer, 
        primary_key=True, 
        autoincrement=True
    )
    
    name: Mapped[str] = mapped_column(
        String, 
        nullable=False
    )
    distance: Mapped[Optional[float]] = mapped_column(
        Float
    )
    geojson: Mapped[Optional[dict]] = mapped_column(
        JSON
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, 
        server_default=func.now(), 
        nullable=False
    )