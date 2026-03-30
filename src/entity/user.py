from src.entity.base import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Integer, String, DateTime, func
from datetime import datetime
from typing import TYPE_CHECKING, List

# 실행 시점이 아닌 타입 체크 시점에만 참조(순환 참조 방지)
if TYPE_CHECKING:
    from src.entity.chat_session import ChatSession

class User(Base):
    """
    사용자 정보를 관리하는 엔티티입니다.
    """
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True
    )
    
    uuid: Mapped[str] = mapped_column(
        String(36),
        unique=True,
        nullable=False,
        index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )

    # 관계 설정: ChatSession과 1:다 관계
    chat_sessions: Mapped[List["ChatSession"]] = relationship(
        "ChatSession",
        back_populates="user",
        cascade="all, delete-orphan"
    )