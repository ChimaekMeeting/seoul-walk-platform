from src.entity.base import Base
from geoalchemy2 import Geometry
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from datetime import datetime
from typing import Optional


class Course(Base):
    """
    런닝/다이어트에 적합한 코스 정보를 관리하는 엔티티입니다.
    """
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False
    )
    course_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="river | park | bike_track | trail"
    )
    is_circular: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="True=순환, False=편도"
    )
    distance_m: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    difficulty: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="easy | medium | hard"
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    source: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True
    )
    geom = mapped_column(
        Geometry("LINESTRING", srid=4326),
        nullable=True
    )
    start_geom = mapped_column(
        Geometry("POINT", srid=4326),
        nullable=True
    )
    end_geom = mapped_column(
        Geometry("POINT", srid=4326),
        nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )

    # 관계 설정: CourseTag와 1:다 관계 (cascade delete)
    tags: Mapped[list[CourseTag]] = relationship(
        "CourseTag",
        back_populates="course",
        cascade="all, delete-orphan"
    )


class CourseTag(Base):
    """
    코스에 붙는 태그 정보를 관리하는 엔티티입니다.
    """
    __tablename__ = "course_tags"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True
    )
    course_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False
    )
    tag: Mapped[str] = mapped_column(
        String(50),
        nullable=False
    )

    # 관계 설정: Course와 다:1 관계
    course: Mapped[Course] = relationship(
        "Course",
        back_populates="tags"
    )
