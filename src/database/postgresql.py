from dotenv import load_dotenv
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager

load_dotenv()

# 환경 변수 로드
DB_HOST = os.getenv("POSTGRES_HOST")
DB_PORT = os.getenv("POSTGRES_PORT")
DB_USER = os.getenv("POSTGRES_USER")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")
DB_NAME = os.getenv("POSTGRES_DB")

# PostgreSQL용 데이터베이스 URL 생성
DATABASE_URL = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Engine 생성
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True  # 연결 유효성 체크
)

# 세션 설정
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@contextmanager
def get_postgresql_db():
    """
    PostgreSQL 연결을 생성하고 사용 후 안전하게 닫습니다.
    """
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()

def health_check() -> bool:
    """
    DB 연결 상태를 확인합니다.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            return True
    except Exception as e:
        return False