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

    # ALT(A* + Landmark + Triangle inequality) 휴리스틱
    # 그래프 로드 직후 랜드마크 거리표를 메모리에 1회 만들어 최단거리 A*에 주입한다.
    # 준비에 실패하면 자동으로 Haversine으로 폴백하므로 기동은 막히지 않는다.
    # 되돌리려면 WALK_ALT_ENABLED=false로 재기동하면 된다.
    WALK_ALT_ENABLED: bool = True
    # Farthest·Avoid는 전처리 비용 대비 이득이 확인되지 않아 지원하지 않는다
    # (analysis/route_engine/alt_landmark_selection_validation.md).
    WALK_ALT_METHOD: Literal["planar", "random"] = "planar"
    # k=8은 2026-09-12 실측으로 확정한 값이다(tier 4개의 Haversine 대비 탐색 시간 비율
    # 평균이 최저). docs/route_engine/README.md "ALT 서비스 연결" 절 참고.
    WALK_ALT_K: int = 8
    # Random 선택법에만 쓰인다. Planar는 좌표 결정론이라 무시한다.
    WALK_ALT_SEED: int = 0

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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14

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
