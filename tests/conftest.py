import sys
import types
import unittest.mock as _mock
import pytest


def _make_mock_module(name):
    mod = types.ModuleType(name)
    mod.__path__ = []
    mod.__package__ = name
    sys.modules[name] = mod
    return mod


def _auto_mock(name):
    parts = name.split(".")
    for i in range(1, len(parts) + 1):
        full = ".".join(parts[:i])
        if full not in sys.modules:
            mod = _make_mock_module(full)
            if i > 1:
                parent = sys.modules.get(".".join(parts[: i - 1]))
                if parent is not None:
                    setattr(parent, parts[i - 1], mod)


# ── 1. 설치되지 않은 외부 패키지 ─────────────────────────────────────────────
for _mod in [
    "redis",
    "redis.asyncio",
    "h3",
    "langchain_core",
    "langchain_core.prompts",
    "langchain_core.output_parsers",
    "langchain_core.tools",
    "langchain_core.messages",
    "langchain_openai",
    "langchain",
    "langchain_community",
    "langgraph",
    "langgraph.graph",
    "geopandas",
    "osmnx",
    "rasterio",
    "rasterio.transform",
    "pyproj",
    "shapely",
    "shapely.geometry",
    "bs4",
]:
    _auto_mock(_mod)

# ── 2. import 시점에 DB/외부 연결을 시도하거나 미설치 패키지를 쓰는 src 모듈 ──
for _mod in [
    # DB 연결
    "src.database.postgresql",
    # Cache 연결
    "src.infrastructure.cache.valkey",
    "src.infrastructure.cache.repository.chat_state_repository",
    # 외부 API 클라이언트
    "src.infrastructure.external.client.kakao_client",
    "src.infrastructure.external.client.gpt_client",
    "src.infrastructure.external.client.weather_client",
    "src.infrastructure.external.client.marathon_client",
    # AI Agent (langgraph 의존)
    "src.agent.nodes",
    "src.agent.nodes.extractor",
    "src.agent.nodes.interviewer",
    "src.agent.nodes.weather_checker",
    "src.agent.nodes.route_executor",
    # Chat service (langgraph 의존)
    "src.service.chat.prewalk_service",
    # Repository (geoalchemy2/h3 의존)
    "src.repository.utils",
    "src.repository.user.user_repository",
    "src.repository.user.user_preference_repository",
    "src.repository.chat.chat_session_repository",
    "src.repository.layer.child_repository",
    "src.repository.layer.landmark_repository",
    "src.repository.layer.nature_repository",
    "src.repository.layer.running_repository",
    "src.repository.layer.safety_repository",
    "src.repository.network.edge_repository",
    "src.repository.network.graph_repository",
    "src.repository.network.node_repository",
    # Route engine (repository 의존)
    "src.route_engine.engines.oneway.running",
    "src.route_engine.engines.oneway.child",
    "src.route_engine.engines.circular.child",
]:
    sys.modules[_mod] = _mock.MagicMock()


# ── 3. 환경변수 자동 주입 ─────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("ACCESS_SECRET_KEY", "test-access-secret")
    monkeypatch.setenv("REFRESH_SECRET_KEY", "test-refresh-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setenv("VALKEY_URI", "redis://localhost:6379/0")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy-key")
