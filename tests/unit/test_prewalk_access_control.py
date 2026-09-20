"""챗봇 State 소유자와 인증 사용자가 다를 때의 접근 차단 회귀 테스트."""

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from src.entity.user import Provider
from src.interfaces.schema.auth_schema import Status
from src.interfaces.schema.prewalk_schema import ChatStatus
from src.schema.prewalk_schema import Location, State


def _load_real_prewalk_service_module():
    source = Path(__file__).parents[2] / "src" / "service" / "chat" / "prewalk_service.py"
    spec = importlib.util.spec_from_file_location("_prewalk_service_access_test", source)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_다른_사용자의_State에는_graph_실행_전에_접근을_차단한다():
    module = _load_real_prewalk_service_module()
    orchestrator = object.__new__(module.PrewalkOrchestrator)
    orchestrator.auth_service = MagicMock()
    orchestrator.auth_service.check_access_token.return_value = (
        Status.SUCCESS,
        Provider.KAKAO,
        "request-user",
    )
    orchestrator.graph = MagicMock()

    module.ChatStateRepository.get_state = AsyncMock(
        return_value=State(
            user_id=999,
            current_location=Location(lat=37.5, lon=127.0),
        )
    )
    module.UserRepository.find_by_provider_and_provider_id = MagicMock(
        return_value=SimpleNamespace(id=1)
    )

    response = asyncio.run(
        orchestrator.orchestrator(
            "request-user-token",
            "other-users-thread",
            "이 경로를 보여줘",
            37.5,
            127.0,
        )
    )

    assert response.status == ChatStatus.UNACCESSIBLE
    orchestrator.graph.ainvoke.assert_not_called()
