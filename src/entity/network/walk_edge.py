from src.entity.base import Base
from geoalchemy2 import Geometry
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, Float, Index, text


class WalkEdge(Base):
    """
    도보 네트워크 엣지(링크) 정보를 관리하는 엔티티입니다.
    """
    __tablename__ = "walk_edges"
    __table_args__ = (
        Index("idx_walk_edges_geog", text("(geom::geography)"), postgresql_using="gist"),
    )

    link_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True
    )
    start_node: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False
    )
    end_node: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False
    )
    length_m: Mapped[float] = mapped_column(
        Float,
        nullable=True
    )
    # 안전·편안 가중 비용(#445)이 읽는 세 점수. 모두 0.0~1.0이다.
    #
    # nullable=True이고 server_default를 두지 않는다 — "아직 계산하지 않음(NULL)"과
    # "계산했고 값이 0(예: 사고 지역과 겹치지 않음)"을 구분해야 하기 때문이다. 기본값
    # 0.0을 주면 미계산 엣지가 "가장 안전한 도로"로 읽혀 안전 가중치를 올릴수록 데이터가
    # 없는 길로 몰린다. 결측 처리는 엣지 단위가 아니라 그래프 단위 커버리지 게이트가
    # 맡는다(scoring/scoring_engine.py::WeightedEdgeCost.check_coverage).
    #
    # 주의: entity/base.py::init_table()(base.py:58-68)은 DB_AUTO_MIGRATE가 off가
    # 아니면 여기 선언된 컬럼을 기동 시 ADD COLUMN으로 만들고, full 모드에서는 선언이
    # 없는 기존 컬럼을 DROP한다(base.py:70-75). 즉 이 선언 자체가 스키마 변경이자,
    # 데이터팀이 채운 컬럼이 full 모드에서 삭제되지 않게 막는 장치다.
    safety_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="안전시설 기반 점수(0.0~1.0). 클수록 안전. NULL은 미계산",
    )
    accident_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="사고위험 점수(0.0~1.0). 클수록 위험. NULL은 미계산",
    )
    slope_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="경사 점수(0.0~1.0). 클수록 평탄. NULL은 미계산",
    )
    '''
    # 아래는 c5d8c13("링크 시설 플래그 제거", 2026-08-25)이 비활성화한 선언을 그대로 둔
    # 것이다. 위의 safety_score/slope_score와 이름이 겹치지만 문자열 안이라 효력이 없다.
    # 되살릴지 여부는 이 블록을 주석 처리한 쪽의 판단이므로 #445에서 건드리지 않는다.
    safety_score: Mapped[float] = mapped_column(
        Float,
        server_default="0.0"
    )
    nature_score: Mapped[float] = mapped_column(
        Float,
        server_default="0.0"
    )
    slope_score: Mapped[float] = mapped_column(
        Float,
        server_default="0.0"
    )
    running_score: Mapped[float] = mapped_column(
        Float,
        server_default="0.0"
    )
    landmark_score: Mapped[float] = mapped_column(
        Float,
        server_default="0.0"
    )
    child_score: Mapped[float] = mapped_column(
        Float,
        server_default="0.0"
    )
    park_overlap_ratio: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        server_default="0.0",
        comment="Edge 길이 중 서울시 공원 Polygon 내부에 포함되는 비율(0.0~1.0)",
    )
    convenience_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        server_default="0.0",
        comment="상권 등 편의 데이터의 Edge 반경 기반 제한 점수(0.0~1.0)",
    )
    is_school_zone: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
        comment="어린이보호구역 Point의 최근접 50m Edge 후보",
    )
    is_vehicle_caution: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
        comment="차량 주의가 필요한 어린이보호구역 인접 Edge",
    )  
    '''
    geom = mapped_column(
        Geometry("LINESTRING", srid=4326, spatial_index=True),
        nullable=False
    )
