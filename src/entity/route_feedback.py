"""
src/entity/route_feedback.py

산책 후 피드백(별점) 엔티티. RouteHistory 1건당 최대 1건 남기며, 장기 프로필
(UserPreference.weights_safety/weights_comfort) 온라인 SGD 갱신의 입력으로 쓰인다.
자세한 갱신 로직은 src/service/user/longterm_profile_service.py 참고.
"""
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.entity.base import Base

if TYPE_CHECKING:
    from src.entity.user import User
    from src.entity.route_history import RouteHistory


class RouteFeedback(Base):
    """
    산책 후 안전/편안/전체 별점(1~5)을 저장하는 엔티티입니다.

    route_history_id는 1:1(경로 하나당 피드백 한 번)로 제한합니다 — 같은 경로에 대한
    재제출은 서비스 레이어에서 upsert로 처리합니다.
    """
    __tablename__ = "route_feedbacks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    route_history_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("route_histories.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    rating_safety:  Mapped[int] = mapped_column(Integer, nullable=False)  # 1~5
    rating_comfort: Mapped[int] = mapped_column(Integer, nullable=False)  # 1~5
    rating_overall: Mapped[int] = mapped_column(Integer, nullable=False)  # 1~5

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship("User")
    route_history: Mapped["RouteHistory"] = relationship("RouteHistory")
