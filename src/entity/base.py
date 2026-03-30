from sqlalchemy.orm import declarative_base
from sqlalchemy import text
from src.database.postgresql import engine

# 모델 생성을 위한 기본 클래스
Base = declarative_base()

def init_db():
    """
    테이블 생성을 위한 초기화 함수입니다.
    """
    # 1. 모든 엔티티 임포트 (Base.metadata에 테이블 정보를 등록하기 위해 필수)
    # dev 브랜치의 통합 임포트 방식을 사용하는 것이 깔끔합니다.
    from src.entity import chat_session, poi_network, route, user_query, user, walk_network

    # 2. PostGIS 확장 설치
    # engine.begin()은 작업이 끝나면 자동으로 commit을 해주므로 더 안전합니다.
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))

    # 3. 테이블 생성
    Base.metadata.create_all(bind=engine)