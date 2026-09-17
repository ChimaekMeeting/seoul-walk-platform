"""
src/entity/user_preference.py

온보딩 설문 결과로 수집한 사용자 경로 선호도 + 산책 후 피드백으로 갱신되는
장기 프로필(long-term profile)을 저장하는 엔티티.
users 테이블과 1:1 관계이며, 설문 미완료 시 경로 추천은 기본 프로필(_DEFAULT)을 사용한다.

장기 프로필 범위 축소(2026-09):
    장기 프로필이 실제로 추적·SGD 갱신하는 축은 안전(safety)과 편안(comfort) 두 개뿐이다
    (산책 후 피드백이 안전/편안/전체 별점 3가지만 받기 때문 — longterm_profile_service 참고).
    나머지 축(자연/경사/러닝/랜드마크/동반/편의/접근성)은 온보딩 시점에만 쓰이고 DB에
    영속되지 않으므로 컬럼을 주석 처리했다. 되살릴 때는 마이그레이션 스크립트
    (scripts/migrate_weights_baseline.py 참고 패턴)로 기존 행에 컬럼을 다시 채워야 한다.
"""
from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.entity.base import Base

if TYPE_CHECKING:
    from src.entity.user import User


class UserPreference(Base):
    """
    사용자 경로 선호도 + 장기 프로필(안전/편안 가중치)을 관리하는 엔티티입니다.

    온보딩 설문 결과가 weights_safety/weights_comfort의 초기값이 되고,
    이후 산책 후 피드백(RouteFeedback)마다 온라인 SGD로 갱신됩니다.
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

    # 장기 프로필(long-term profile) — 산책 후 피드백 기반 온라인 SGD로 갱신되는 두 축.
    weights_safety:  Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    weights_comfort: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # 지금까지 반영된 피드백 개수. 적응형 학습률(η)을 결정하는 데 쓰인다
    # (longterm_profile_service._adaptive_learning_rate 참고) — 평가가 쌓일수록 η가 줄어든다.
    feedback_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # --- 장기 프로필 범위 밖: 온보딩 시점에만 계산되고 DB에는 저장하지 않는 축들.
    # 필요해지면 컬럼을 되살리고 migrate 스크립트로 기존 행을 채운 뒤 주석을 해제한다.
    # weights_nature:       Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # weights_slope:        Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # weights_running:      Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # weights_landmark:     Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # weights_child:        Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # weights_convenience:  Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # weights_accessibility: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    selected_tags: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="user_preference")
