from sqlalchemy.orm import declarative_base
from sqlalchemy import text
from src.database.postgresql import engine

# 모델 생성을 위한 기본 클래스
Base = declarative_base()

def init_db():
    """
    테이블 생성을 위한 초기화 함수입니다.
    """
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.commit()
        
    from src.entity import chat_session, poi_network, route, user_query, user, walk_network
    
    Base.metadata.create_all(bind=engine)