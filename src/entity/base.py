from sqlalchemy.orm import declarative_base
from src.database.postgresql import engine
from sqlalchemy import text

# 모델 생성을 위한 기본 클래스
Base = declarative_base()


def init_db():
    """
    테이블 생성을 위한 초기화 함수입니다.
    """
    from src.entity.route import Route
    from src.entity.user_query import UserQuery
    from src.entity.walk_network import WalkNode, WalkEdge
    from src.entity.poi_network import SafetyPoint, PoiPoint

    # 🌟 추가된 부분: 테이블 생성 전에 postgis 확장을 먼저 설치합니다.
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))

    Base.metadata.create_all(bind=engine)
