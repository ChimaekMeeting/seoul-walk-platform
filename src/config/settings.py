import os
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # PostgreSQL
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "seoul_walk"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5434
    # "" = SSL 없음 (로컬), "require" = TLS 필수 (Supabase)
    POSTGRES_SSL_MODE: str = ""
    # Supabase Session Pooler 한도 대응: 인스턴스당 최대 5 커넥션 (2+3)
    DB_POOL_SIZE: int = 2
    DB_MAX_OVERFLOW: int = 3

    # Walk Graph
    WALK_GRAPH_SOURCE: Literal["database", "artifact"] = "database"
    WALK_GRAPH_ARTIFACT_PATH: str = "artifacts/walk_graph_v1.pkl"
    WALK_GRAPH_DATA_VERSION: str = "v1-2026-07-30"
    WALK_GRAPH_EXPECTED_COMMIT: str = ""

    # Valkey
    VALKEY_URI: str = "redis://localhost:6379"

    # Map
    MAPBOX_API_KEY: str = ""
    KAKAO_API_KEY: str = ""
    KAKAO_REDIRECT_URI: str = "http://localhost:8501"

    # Weather
    WEATHER_API_KEY: str = ""
    AIR_KOREA_API_KEY: str = ""

    # OpenAI
    OPENAI_API_KEY: str = ""

    # Public Data
    PUBLIC_DATA_API_KEY: str = ""

    # JWT
    ACCESS_SECRET_KEY: str = ""
    REFRESH_SECRET_KEY: str = ""

    # LangSmith
    LANGCHAIN_TRACING_V2: str = "false"
    LANGCHAIN_ENDPOINT: str = "https://api.smith.langchain.com"
    LANGCHAIN_API_KEY: str = ""
    LANGCHAIN_PROJECT: str = ""

    # DB 마이그레이션 모드
    # full  : CREATE TABLE + ADD COLUMN + DROP COLUMN (기본값, 로컬 개발)
    # create: CREATE TABLE + ADD COLUMN only          (프로덕션 권장)
    # off   : 스키마 변경 전혀 없음                      (완전 수동 관리)
    DB_AUTO_MIGRATE: str = "full"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()

# LangChain이 import되기 전에 os.environ에 반영되어야 트레이싱이 활성화됨
os.environ["LANGCHAIN_TRACING_V2"] = settings.LANGCHAIN_TRACING_V2
os.environ["LANGCHAIN_ENDPOINT"] = settings.LANGCHAIN_ENDPOINT
os.environ["LANGCHAIN_API_KEY"] = settings.LANGCHAIN_API_KEY
os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT
