from typing import Optional

from src.entity.base import Base
from geoalchemy2 import Geometry
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, Float, Index, text


class WalkNode(Base):
    """
    도보 네트워크 노드 정보를 관리하는 엔티티입니다.
    """
    __tablename__ = "walk_nodes"
    __table_args__ = (
        Index("idx_walk_nodes_geog", text("(geom::geography)"), postgresql_using="gist"),
    )

    node_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True
    )
    geom = mapped_column(
        Geometry("POINT", srid=4326),
        nullable=False
    )
    # SlopeCalculator가 DEM에서 샘플링해 채우는 노드 고도(m). NodeRepository가
    # ensure_column("elevation_m")으로 런타임에만 채워온 컬럼이라 ORM 선언이
    # 계속 빠지곤 하는데, DB_AUTO_MIGRATE=full(settings.py 기본값)에서는 선언 없는
    # 기존 컬럼을 init_table()이 DROP하므로 명시적으로 선언해 보호한다. nullable=True인
    # 이유는 walk_edge.py의 safety_score 등과 동일 — "아직 계산 안 함(NULL)"과
    # "계산했고 값이 0"을 구분해야 한다.
    elevation_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
