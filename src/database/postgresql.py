from dotenv import load_dotenv
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager

load_dotenv(encoding="utf-8")

# 환경 변수에서 DB 접속 정보를 로드합니다.
DB_HOST = os.getenv("POSTGRES_HOST")
DB_PORT = os.getenv("POSTGRES_PORT")
DB_USER = os.getenv("POSTGRES_USER")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")
DB_NAME = os.getenv("POSTGRES_DB")

# POSTGRES_SSL_MODE=require → Supabase 등 TLS 필수 환경
# POSTGRES_SSL_MODE="" (기본) → 로컬 개발 (SSL 없음)
_ssl_mode = os.getenv("POSTGRES_SSL_MODE", "")
_ssl_param = f"&sslmode={_ssl_mode}" if _ssl_mode else ""

DATABASE_URL = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?client_encoding=utf8{_ssl_param}"

# Supabase Session Pooler 최대 15 커넥션 (max-instances=3 × 5 = 15 초과 방지)
# pool_size=2, max_overflow=3 → 인스턴스당 최대 5 커넥션 → 3 인스턴스 × 5 = 15
_pool_size = int(os.getenv("DB_POOL_SIZE", "2"))
_max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "3"))

engine = create_engine(
    DATABASE_URL,
    pool_size=_pool_size,
    max_overflow=_max_overflow,
    pool_pre_ping=True,  # Supabase 유휴 커넥션 자동 복구
)

# 세션 팩토리를 설정합니다.
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
