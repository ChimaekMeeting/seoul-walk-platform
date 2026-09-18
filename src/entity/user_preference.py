"""
src/entity/user_preference.py

온보딩 설문 결과로 수집한 사용자 경로 선호도를 저장하는 엔티티.
users 테이블과 1:1 관계이며, 설문 미완료 시 경로 추천은 기본 프로필(_DEFAULT)을 사용한다.
"""
from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.entity.base import Base

if TYPE_CHECKING:
    from src.entity.user import User


class UserPreference(Base):
    """
    사용자 경로 선호도를 관리하는 엔티티입니다.

    온보딩 설문의 키워드 태그 선택 결과가 각 weights 컬럼에 저장됩니다.
    null인 가중치는 경로 생성 시 해당 프로필의 기본값으로 대체됩니다.
    """
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True
    )

    survey_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_target_km: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 2026-09-17: 챗봇 가중치 개인화를 안전/편안 두 축으로 좁히며 나머지 6개 컬럼
    # (nature/slope/running/landmark/child/convenience/accessibility)을 제거하고
    # weights_comfort를 새로 추가했다. DB_AUTO_MIGRATE=full이면 다음 서버
    # 재시작 시 드랍된 컬럼의 기존 데이터가 함께 삭제된다(백업 없이 진행하기로 확인).
    weights_safety: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    weights_comfort: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    selected_tags: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="user_preference")
