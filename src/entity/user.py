from src.entity.base import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Integer, String, DateTime, func
from datetime import datetime
from typing import TYPE_CHECKING, List

# 순환 참조를 방지하기 위해 타입 체크 시점에만 참조합니다.
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

    # ChatSession과 1:다 관계를 설정합니다.
    chat_sessions: Mapped[List["ChatSession"]] = relationship(
        "ChatSession",
        back_populates="user",
        cascade="all, delete-orphan"
    )