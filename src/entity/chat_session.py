import enum

from src.entity.base import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Integer, String, DateTime, Enum, ForeignKey, func
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.entity.user import User


class SessionState(enum.Enum):
    START = "START"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class ChatSession(Base):
    """
    사용자와 챗봇 간의 세션 정보를 관리하는 엔티티입니다.
    """
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False
    )
    thread_id: Mapped[str] = mapped_column(
        String(36),
        unique=True,
        nullable=False
    )
    current_state: Mapped[SessionState] = mapped_column(
        Enum(SessionState, native_enum=False),
        default=SessionState.START,
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    # 관계 설정: User와 다:1 관계
    user: Mapped["User"] = relationship(
        "User",
        back_populates="chat_sessions"
    )
