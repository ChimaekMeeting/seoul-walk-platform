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
    # 장기 프로필 SGD의 X_contrast 계산용 스냅샷. index 0 = 이 history가 나타내는 실제
    # 선택 가능 경로, 나머지는 같은 요청에서 함께 생성된 비교 후보(최대 2개)다. 여러 후보를
    # 반환하면 후보마다 별도 history를 만들고 자기 특성이 index 0이 되도록 목록을 회전한다.
    # 각 원소는 {"safety": 0~1, "comfort": 0~1} (scoring_engine.path_feature_averages).
    # 특성 스냅샷을 만들 수 없는 경우에만 None이다.
    candidate_features: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="route_histories")
