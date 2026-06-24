from src.entity.base import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Integer, String, Float, DateTime, JSON, ForeignKey, func
from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.entity.user import User


class RouteHistory(Base):
    __tablename__ = "route_histories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False
    )
    mode: Mapped[str] = mapped_column(String(50), nullable=False)
    origin_lat: Mapped[float] = mapped_column(Float, nullable=False)
    origin_lon: Mapped[float] = mapped_column(Float, nullable=False)
    destination_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    destination_lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    coordinates: Mapped[list] = mapped_column(JSON, nullable=False)
    total_km: Mapped[float] = mapped_column(Float, nullable=False)
    is_favorite: Mapped[bool] = mapped_column(
        default=False, server_default="false", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="route_histories")
