from src.entity.base import Base
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Integer, String, DateTime, func, JSON
from datetime import datetime
from typing import Optional

class UserQuery(Base):
    """
    사용자가 입력한 원본 질문과 이를 분석(Parsing)한 결과를 저장합니다.
    """
    __tablename__ = "user_queries"

    id: Mapped[int] = mapped_column(
        Integer, 
        primary_key=True, 
        autoincrement=True
    )

    raw_text: Mapped[str] = mapped_column(
        String, 
        nullable=False
    )

    parsed: Mapped[Optional[dict]] = mapped_column(
        JSON
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, 
        server_default=func.now(), 
        nullable=False
    )