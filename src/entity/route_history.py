from src.entity.base import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Integer, String, Float, DateTime, Date, Index, JSON, ForeignKey, Text, func
from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.entity.user import User


class RouteHistory(Base):
    __tablename__ = "route_histories"
    # 같은 사용자의 같은 경로(route_hash)를 묶어 조회하기 위한 복합 인덱스(#524). UNIQUE는 두지 않는다 —
    # 같은 경로를 여러 번 산책할 수 있다. init_table()이 기존 테이블에도 누락된 인덱스를 만든다.
    __table_args__ = (Index("ix_route_histories_user_id_route_hash", "user_id", "route_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False
    )
    mode: Mapped[str] = mapped_column(String(50), nullable=False)
    origin_lat: Mapped[float] = mapped_column(Float, nullable=False)
    origin_lon: Mapped[float] = mapped_column(Float, nullable=False)
    destination_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    destination_lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    coordinates: Mapped[list] = mapped_column(JSON, nullable=False)
    total_km: Mapped[float] = mapped_column(Float, nullable=False)
    is_favorite: Mapped[bool] = mapped_column(
        default=False, server_default="false", nullable=False
    )
    # 장기 프로필 SGD의 X_contrast 계산용 스냅샷. index 0 = 이 history가 나타내는 실제
    # 선택 가능 경로, 나머지는 같은 요청에서 함께 생성된 비교 후보(최대 2개)다. 여러 후보를
    # 반환하면 후보마다 별도 history를 만들고 자기 특성이 index 0이 되도록 목록을 회전한다.
    # 각 원소는 {"safety": 0~1, "comfort": 0~1} (scoring_engine.path_feature_averages).
    # 특성 스냅샷을 만들 수 없는 경우에만 None이다.
    candidate_features: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )

    # 출발지/도착지 표시용 이름(#520). 챗봇 state의 Location(address, place_name)에서 채우고,
    # 챗봇을 거치지 않은 경로(직접 경로 API)와 이 컬럼이 생기기 전 기록은 None이다.
    origin_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    origin_place_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    destination_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    destination_place_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 산책 진행 상태(#520): recommended(추천만 받음) -> in_progress(산책 시작) -> completed(완주).
    # 문자열로 저장한다(WalkProgressStatus). 이 컬럼이 생기기 전 기록은 init_table()의 ADD COLUMN이
    # 기본값 없이 NULL로 추가하므로 None은 recommended로 읽는다(is_favorite과 같은 처리).
    walk_status: Mapped[str] = mapped_column(
        String(20), default="recommended", server_default="recommended", nullable=False
    )
    # 가장 최근에 완주한 날짜(한국 시간 기준). 완주로 기록할 때마다 그날 날짜로 덮어쓰므로 재산책하면
    # 갱신되고 최초 완주일은 남지 않는다. 완주한 적 없는 경로는 None이다.
    # 사용자의 최근 산책은 이 날짜가 가장 늦은 기록이다.
    walked_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # 같은 경로 식별자(#524). 좌표를 정규화해 SHA-256한 64자리 hex이고, 규칙은 route_hash_version으로 구분한다
    # (repository/user/route_hash.py). 이 컬럼이 생기기 전 기록과 hash를 만들 수 없던 기록은 둘 다 None이다.
    # route_hash_version에 DB DEFAULT를 두지 않는다 — init_table()의 ADD COLUMN은 DEFAULT를 붙이지 못해
    # 새 DB와 마이그레이션한 DB의 행이 달라지고, hash 없는 행에 버전만 붙으면 "hash 있음"으로 오해하기 때문이다.
    route_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    route_hash_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="route_histories")
