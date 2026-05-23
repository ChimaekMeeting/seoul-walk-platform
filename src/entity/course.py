"""
런닝/다이어트 모드 전용 코스 엔티티

COURSE      : 하천변·공원 기반 코스 메타데이터
COURSE_TAG  : 코스에 붙는 태그 (런닝, 다이어트, 하천변, 공원 등)
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.entity.base import Base


class Course(Base):
    """
    런닝/다이어트에 적합한 코스 정보.

    Columns
    -------
    id              : PK
    name            : 코스 이름 (예: '한강 반포 구간')
    course_type     : 'river' | 'park' | 'bike_track'
    is_circular     : True → 순환 코스, False → 편도 코스
    distance_m      : 총 거리 (미터)
    difficulty      : 'easy' | 'medium' | 'hard'
    description     : 코스 설명
    source          : 원본 데이터 출처
    geom            : LINESTRING (경로 전체 선형 지오메트리)
    start_geom      : POINT (출발점)
    end_geom        : POINT (도착점, 순환이면 start_geom 과 동일)
    created_at      : 생성 시각
    """

    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    course_type: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="river | park | bike_track | trail"
    )
    is_circular: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="True=순환, False=편도"
    )
    distance_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    difficulty: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, comment="easy | medium | hard"
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # PostGIS 지오메트리
    geom = mapped_column(
        Geometry("LINESTRING", srid=4326),
        nullable=True,
        comment="코스 전체 경로 선형",
    )
    start_geom = mapped_column(
        Geometry("POINT", srid=4326),
        nullable=True,
        comment="출발점",
    )
    end_geom = mapped_column(
        Geometry("POINT", srid=4326),
        nullable=True,
        comment="도착점 (순환이면 출발점과 동일)",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # 관계
    tags: Mapped[list[CourseTag]] = relationship(
        "CourseTag", back_populates="course", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Course id={self.id} name={self.name!r} type={self.course_type}>"


class CourseTag(Base):
    """
    코스에 붙는 태그.

    예시 태그: '런닝', '다이어트', '하천변', '공원', '자전거도로', '야간가능'
    """

    __tablename__ = "course_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    tag: Mapped[str] = mapped_column(String(50), nullable=False)

    # 관계
    course: Mapped[Course] = relationship("Course", back_populates="tags")

    def __repr__(self) -> str:
        return f"<CourseTag course_id={self.course_id} tag={self.tag!r}>"
