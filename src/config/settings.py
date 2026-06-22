import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # PostgreSQL
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "seoul_walk"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5434

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

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()

# LangChain이 import되기 전에 os.environ에 반영되어야 트레이싱이 활성화됨
os.environ["LANGCHAIN_TRACING_V2"] = settings.LANGCHAIN_TRACING_V2
os.environ["LANGCHAIN_ENDPOINT"] = settings.LANGCHAIN_ENDPOINT
os.environ["LANGCHAIN_API_KEY"] = settings.LANGCHAIN_API_KEY
os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT
