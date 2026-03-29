from src.entity.base import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Integer, String, DateTime, func, ForeignKey, Enum
from datetime import datetime
from typing import TYPE_CHECKING
import enum

# 실행 시점이 아닌 타입 체크 시점에만 참조(순환 참조 방지)
if TYPE_CHECKING:
    from src.entity.user import User

class SessionState(enum.Enum):
    START = "START"              # 대화 시작
    IN_PROGRESS = "IN_PROGRESS"  # 정보 수집 및 대화 중
    COMPLETED = "COMPLETED"      # 대화 종료

class ChatSession(Base):
    """
    사용자와 챗봇 간의 전체적인 세션을 관리합니다.
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
        Enum(SessionState, native_enum=False),  # DB에는 문자열로 저장
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