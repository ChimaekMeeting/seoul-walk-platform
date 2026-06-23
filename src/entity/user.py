from src.entity.base import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Integer, String, DateTime, func, Enum, UniqueConstraint
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
import enum

# 순환 참조를 방지하기 위해 타입 체크 시점에만 참조합니다.
if TYPE_CHECKING:
    from src.entity.chat_session import ChatSession
    from src.entity.user_preference import UserPreference

class Provider(str, enum.Enum):
    KAKAO = "kakao"

class User(Base):
    """
    사용자 정보를 관리하는 엔티티입니다.
    """
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("provider", "provider_id", name="provider_identity"),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True
    )
    
    provider: Mapped[Provider] = mapped_column(
        Enum(Provider),
        nullable=True,
    )
    provider_id: Mapped[str] = mapped_column(
        String(255),
        nullable=True,
        index=True
    )
    nickname: Mapped[str] = mapped_column(
        String(50),
        nullable=True
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

    # UserPreference와 1:1 관계를 설정합니다.
    user_preference: Mapped[Optional["UserPreference"]] = relationship(
        "UserPreference",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan"
    )
